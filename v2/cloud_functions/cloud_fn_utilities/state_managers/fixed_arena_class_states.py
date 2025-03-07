import time
from datetime import datetime
from enum import Enum
import logging

from cloud_fn_utilities.gcp.datastore_manager import DataStoreManager
from cloud_fn_utilities.globals import DatastoreKeyTypes, ServerStates, FixedArenaClassStates

__author__ = "Philip Huff"
__copyright__ = "Copyright 2022, UA Little Rock, Emerging Analytics Center"
__credits__ = ["Philip Huff"]
__license__ = "MIT"
__version__ = "1.0.0"
__maintainer__ = "Philip Huff"
__email__ = "pdhuff@ualr.edu"
__status__ = "Testing"


class FixedArenaClassStateManager:
    class ServerStateCheck(Enum):
        READY = 0
        RUNNING = 1
        DELETED = 2

    COMPLETION_STATES = [FixedArenaClassStates.COMPLETED_DELETING_SERVERS, FixedArenaClassStates.COMPLETED_ROUTES,
                         FixedArenaClassStates.COMPLETED_SERVERS]

    MAX_WAIT_TIME = 300
    SLEEP_TIME = 10

    def __init__(self, initial_build_id=None):
        self.s = FixedArenaClassStates
        self.server_states = ServerStates
        self.build_id = initial_build_id
        if self.build_id:
            self.ds = DataStoreManager(key_type=DatastoreKeyTypes.FIXED_ARENA_CLASS, key_id=self.build_id)
            self.build = self.ds.get()
            if 'state' not in self.build:
                self.build['state'] = self.s.START.value
                self.build['state-timestamp'] = datetime.utcnow().isoformat()
        else:
            self.ds = None
            self.build = None

    def set_build_record(self, build_id):
        self.build_id = build_id
        self.ds = DataStoreManager(key_type=DatastoreKeyTypes.FIXED_ARENA_CLASS, key_id=self.build)
        self.build = self.ds.get()
        if 'state' not in self.build:
            self.build['state'] = self.s.START.value
            self.build['state-timestamp'] = datetime.utcnow().isoformat()

    def state_transition(self, new_state):
        """
        Consistently changes a datastore entity with the necessary state checks.
        :param entity: A datastore entity
        :param new_state: The new state for the server
        :return: Boolean on success. If the state transition is valid, then return True. Otherwise, return False
        """
        existing_state = self.s(self.build['state'])
        if self._is_fixed_arena_valid_transition(existing_state, new_state):
            self.build['state'] = new_state.value
            self.build['state-timestamp'] = datetime.utcnow().isoformat()
            if new_state == self.s.DELETED:
                self.build['active'] = False
            elif new_state == self.s.READY:
                self.build['active'] = True
            logging.info(f"State Transition {self.build.key.name}: Transitioning from {existing_state.name} to "
                         f"{new_state.name}")
            self.ds.put(self.build)
            return True
        else:
            return False

    def get_state(self):
        return self.build['state']

    def get_state_timestamp(self):
        return self.build['state-timestamp']

    def are_server_builds_finished(self):
        return self._server_state_check(server_states=[self.server_states.STOPPED.value])

    def are_servers_started(self):
        return self._server_state_check(server_states=[self.server_states.RUNNING.value])

    def are_servers_stopped(self):
        return self._server_state_check(server_states=[self.server_states.STOPPED.value])

    def are_servers_deleted(self):
        return self._server_state_check(server_states=[self.server_states.DELETED.value])

    def _server_state_check(self, server_states):
        wait_time = 0
        check_complete = False
        workspaces = self.ds.get_children(child_key_type=DatastoreKeyTypes.FIXED_ARENA_WORKSPACE,
                                          parent_id=self.build_id)
        while not check_complete and wait_time < self.MAX_WAIT_TIME:
            check_complete = True
            servers = self.ds.get_servers()
            for server in servers:
                if server.get('state', None) not in server_states:
                    check_complete = False
                    continue
            for workspace in workspaces:
                ws_id = workspace.key.name
                ws_ds = DataStoreManager(key_type=DatastoreKeyTypes.FIXED_ARENA_WORKSPACE, key_id=ws_id)
                ws_servers = ws_ds.get_servers()
                for ws_server in ws_servers:
                    if ws_server.get('state', None) not in server_states:
                        check_complete = False
                        continue
            # Only run this conditional if looking for servers to start. Fixed arena servers are not built or deleted
            # with the fixed-arena-class
            # does not work because cln-stoc-webserver does not keep track of its state in the datastore so it returns
            # a null type and not a int which throws a type error.
            if self.server_states.RUNNING.value in server_states:
                for server in self.build['fixed_arena_servers']:
                    server_name = f"{self.build['parent_id']}-{server}"
                    server_ds = DataStoreManager(key_type=DatastoreKeyTypes.SERVER, key_id=server_name).get()
                    server_state = server_ds.get('state', None)
                    if server_state not in server_states:
                        check_complete = False
                        continue
            if not check_complete:
                time.sleep(self.SLEEP_TIME)
                wait_time += self.SLEEP_TIME
        if check_complete:
            return True
        else:
            return False

    def _is_fixed_arena_valid_transition(self, existing_state, new_state):
        new_state = self.s(new_state)
        if new_state == self.s.START and not existing_state:
            return True
        elif new_state == self.s.BUILDING_ASSESSMENT and existing_state in [self.s.START, self.s.BROKEN]:
            return True
        elif new_state in [self.s.BUILDING_SERVERS, self.s.BUILDING_STUDENT_ENTRY] \
                and existing_state.value < new_state.value:
            return True
        elif new_state == self.s.BUILDING_STUDENT_ENTRY and existing_state.value < new_state.value:
            return True
        elif new_state == self.s.READY and existing_state in [self.COMPLETION_STATES, self.s.BUILDING_STUDENT_ENTRY]:
            return True
        elif new_state in self.COMPLETION_STATES:
            return True
        elif new_state in [self.s.RUNNING, self.s.BROKEN, self.s.DELETED, self.s.READY, self.s.STOPPED]:
            return True
        else:
            logging.warning(f"Invalid build state transition! Attempting to move to {self.s(new_state).name}, but "
                            f"the build is currently in the state {self.s(existing_state).name}")
            return False
