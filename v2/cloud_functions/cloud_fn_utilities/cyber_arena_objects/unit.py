import json
import logging
import random
import string
from datetime import datetime, timezone

from cloud_fn_utilities.gcp.cloud_env import CloudEnv
from cloud_fn_utilities.gcp.datastore_manager import DataStoreManager
from cloud_fn_utilities.gcp.pubsub_manager import PubSubManager
from cloud_fn_utilities.gcp.cloud_logger import Logger
from cloud_fn_utilities.globals import DatastoreKeyTypes, PubSub, BuildConstants, UnitStates, WorkoutStates, \
    get_current_timestamp_utc
from cloud_fn_utilities.cyber_arena_objects.workout import Workout
from cloud_fn_utilities.state_managers.unit_states import UnitStateManager
from cloud_fn_utilities.lms.canvas.lms_canvas import LMSCanvas

__author__ = "Philip Huff"
__copyright__ = "Copyright 2022, UA Little Rock, Emerging Analytics Center"
__credits__ = ["Philip Huff"]
__license__ = "MIT"
__version__ = "1.0.0"
__maintainer__ = "Philip Huff"
__email__ = "pdhuff@ualr.edu"
__status__ = "Testing"


class Unit:
    def __init__(self, build_id, child_id=None, form_data=None, debug=False, force=False, env_dict=None):
        """

        Args:
            build_id (str): The Unit ID to manage
            child_id (str): A Workout ID if the intent is to build a new workout
            form_data (str): Use associated with web form. This includes keys for student_name, student_email and
                        team_name (for escape rooms)
            debug (bool): Avoids pubsub messages and builds synchronously
            force (bool): Unused
            env_dict (dict): A boolean of dictionary values to avoid hitting the datastore
        """
        self.unit_id = build_id
        self.debug = debug
        self.force = force
        self.env = CloudEnv(env_dict=env_dict) if env_dict else CloudEnv()
        self.env_dict = self.env.get_env()
        self.logger = Logger("cloud_functions.unit").logger
        self.s = UnitStates
        self.pubsub_manager = PubSubManager(PubSub.Topics.CYBER_ARENA.value, env_dict=self.env_dict)
        self.ds_unit = DataStoreManager(key_type=DatastoreKeyTypes.UNIT, key_id=self.unit_id)
        self.ds_workout = DataStoreManager(key_type=DatastoreKeyTypes.WORKOUT)
        self.unit = self.ds_unit.get()
        if not self.unit:
            self.logger.error(f"The datastore record for {self.unit_id} no longer exists!")
            raise LookupError
        self.lms_integration = True if self.unit.get('lms_connection') else False
        self.lms_quiz = True if self.unit.get('lms_quiz', None) else False

        # Pass in these values to build a single workout associated with the unit
        self.child_id = child_id  # id to use for child workout
        self.form_data = form_data  # dictionary in JSON formatted string

    def build(self):
        if self.lms_integration:
            self._create_unit_for_lms()
            self.ds_unit.put(self.unit)
        else:
            if not self.lms_integration:
                if not self.child_id:
                    logging.error(f"No build id provided for build handler with action {self.unit['build_type']}")
                    raise ValueError
                elif not self.form_data:
                    logging.error(f'Missing claimed_by data for build handler with action {self.unit["build_type"]}')
                    raise ValueError
                self.form_data = json.loads(self.form_data)
            self._build_one_workout(workout_id=self.child_id)

    def start(self):
        workouts = self.ds_unit.get_children(child_key_type=DatastoreKeyTypes.WORKOUT, parent_id=self.unit_id)
        for workout in workouts:
            if self.debug:
                workout = Workout(build_id=str(workout.key.name), debug=self.debug, env_dict=self.env_dict)
                workout.delete()
            else:
                self.pubsub_manager.msg(handler=str(PubSub.Handlers.CONTROL.value),
                                        action=str(PubSub.Actions.START.value),
                                        cyber_arena_object=str(PubSub.CyberArenaObjects.WORKOUT.value),
                                        build_id=str(workout.key.name))

    def stop(self):
        workouts = self.ds_unit.get_children(child_key_type=DatastoreKeyTypes.WORKOUT, parent_id=self.unit_id)
        for workout in workouts:
            Workout(build_id=workout.key.name, debug=self.debug, env_dict=self.env_dict).stop()

    def delete(self):
        workouts = self.ds_unit.get_children(child_key_type=DatastoreKeyTypes.WORKOUT, parent_id=self.unit_id)
        for workout in workouts:
            if self.debug:
                Workout(build_id=workout.key.name, debug=self.debug, env_dict=self.env_dict).delete()
            else:
                self.pubsub_manager.msg(handler=str(PubSub.Handlers.CONTROL.value),
                                        action=str(PubSub.Actions.DELETE.value),
                                        cyber_arena_object=str(PubSub.CyberArenaObjects.WORKOUT.value),
                                        build_id=str(workout.key.name))
        unit_state_manager = UnitStateManager(build_id=self.unit_id)
        if unit_state_manager.are_workouts_deleted():
            unit_state_manager.state_transition(new_state=UnitStates.DELETED)
        else:
            self.logger.error(f"Unit {self.unit_id} is not deleted!")

    def nuke(self):
        workouts = self.ds_unit.get_children(child_key_type=DatastoreKeyTypes.WORKOUT, parent_id=self.unit_id)
        for workout in workouts:
            Workout(build_id=workout.key.name, debug=self.debug, env_dict=self.env_dict).nuke()

    def mark_broken(self):
        self.unit['state'] = self.s.BROKEN
        self.ds_unit.put(self.unit)

    def get_build_id(self):
        return self.unit_id

    def add_student_workout_record(self, student_email, student_name):
        """
        Creates a workout record for the unit without building it. This is initially used for synchronizing with the
        LMS when new students are added to the course. The LMS sync get called in the hourly maintenance function.
        Args:
            student_email (str): The email address of the student
            student_name (str): The name of the student

        Returns: None

        """
        workout_id = ''.join(random.choice(string.ascii_lowercase) for j in range(10))
        workout_record = self._create_workout_record(workout_id=workout_id)
        workout_record['student_email'] = student_email.lower()
        workout_record['student_name'] = student_name
        self.ds_workout.put(workout_record, key_type=DatastoreKeyTypes.WORKOUT, key_id=workout_id)

    def _create_unit_for_lms(self):
        lms_type = self.unit['lms_connection']['lms_type']
        url = self.unit['lms_connection']['url']
        api_key = self.unit['lms_connection']['api_key']
        course_code = self.unit['lms_connection']['course_code']
        if lms_type == BuildConstants.LMS.CANVAS:
            lms = LMSCanvas(url=url, api_key=api_key, course_code=course_code, build=self.unit)
        else:
            self.logger.error(f"Unsupported LMS object")
            raise ValueError

        if self.unit.get('lms_quiz', None):
            lms.create_quiz()
            self.unit = lms.get_updated_build()  # Prevents overwriting the unit after the quiz has been updated
        else:
            lms.create_assignment()
        students = lms.get_class_list()
        for student in students:
            workout_id = ''.join(random.choice(string.ascii_lowercase) for j in range(10))
            workout_record = self._create_workout_record(workout_id=workout_id)
            workout_record['student_email'] = student.get('email').lower()
            workout_record['student_name'] = student.get('name')
            self.ds_workout.put(workout_record, key_type=DatastoreKeyTypes.WORKOUT, key_id=workout_id)

    def _build_one_workout(self, workout_id):
        count = min(int(self.env.max_workspaces), int(self.unit['workspace_settings']['count']))
        workout_list = DataStoreManager(key_type=DatastoreKeyTypes.WORKOUT).query(
            filters=[('parent_id', '=', self.unit_id)])
        if workout_list:
            if len(workout_list) >= count:
                self.logger.error(f"Requested build for unit {self.unit_id} failed; Unit is at max capacity")
                raise ValueError
        student_email = self.form_data.get('student_email', None)
        team_name = self.form_data.get('team_name', None)
        if student_email:
            workout_record = self._create_workout_record(workout_id=workout_id)
            workout_record['student_email'] = student_email
            student_name = self.form_data.get('student_name', None)
            if student_name:
                workout_record['student_name'] = student_name
        elif team_name:
            workout_record = self._create_workout_record(workout_id=workout_id)
            workout_record['team_name'] = team_name
        else:
            self.logger.error(f'Invalid or missing claimed_by values given for unit {self.unit_id}')
            raise ValueError
        self.ds_workout.put(workout_record, key_type=DatastoreKeyTypes.WORKOUT, key_id=workout_id)
        if self.debug:
            workout = Workout(build_id=workout_id, debug=self.debug, env_dict=self.env_dict)
            workout.build()
        else:
            self.pubsub_manager.msg(handler=str(PubSub.Handlers.BUILD.value),
                                    action=str(PubSub.BuildActions.WORKOUT.value),
                                    key_type=str(DatastoreKeyTypes.WORKOUT.value),
                                    build_id=str(workout_id))

    def _create_workout_record(self, workout_id):
        workout_record = {
            'id': workout_id,
            'parent_id': self.unit_id,
            'parent_build_type': BuildConstants.BuildType.UNIT,
            'build_type': BuildConstants.BuildType.WORKOUT,
            'creation_timestamp': datetime.now(timezone.utc).replace(tzinfo=timezone.utc).timestamp(),
            'state': WorkoutStates.NOT_BUILT.value,
        }
        if workout_duration_days := self.unit.get('workout_duration_days', None):
            workout_record['expiration'] = get_current_timestamp_utc(add_seconds=86400*workout_duration_days)
        if self.unit.get('networks'):
            workout_record['networks'] = self.unit['networks']
            workout_record['servers'] = self.unit['servers']
            workout_record['firewall_rules'] = self.unit.get('firewall_rules', None)
        if self.unit.get('web_applications'):
            processed_web_applications = []
            for web_application in self.unit['web_applications']:
                processed_web_application = {
                    'name': web_application['name'],
                    'url': f"https://{web_application['host_name']}{self.env.dns_suffix}"
                           f"{web_application['starting_directory']}/{workout_id}",
                    'starting_directory': web_application['starting_directory'],
                }
                processed_web_applications.append(processed_web_application)
            workout_record['web_applications'] = processed_web_applications
        escape_room_spec = self.unit.get('escape_room', None)
        if escape_room_spec:
            workout_record['escape_room'] = escape_room_spec
        else:
            if assessment := self.unit.get('assessment', None):
                workout_record['assessment'] = assessment
            elif lms_quiz := self.unit.get('lms_quiz', None):
                workout_record['lms_quiz'] = lms_quiz
        if self.debug:
            workout_record['test'] = True
        return workout_record
