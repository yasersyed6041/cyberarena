from flask import Blueprint, request, redirect
from utilities.pubsub_functions import pub_admin_scripts, pub_manage_server
from utilities.globals import ds_client, project, log_client, compute, zone, LOG_LEVELS, AdminActions, workout_globals
from utilities.yaml_functions import YamlFunctions
from utilities.datastore_functions import store_custom_logo, store_background_color, upload_instruction_file
from utilities.iot_manager import IotManager
import json
import datetime

admin_api = Blueprint('admin_api', __name__, url_prefix='/api')


@admin_api.route('/active_workouts', methods=['GET'])
def get_active_workouts():
    active_workout_query = ds_client.query(kind='cybergym-workout')
    
    workout_list = active_workout_query.fetch()
    active_workouts = []

    for workout in workout_list:
        if 'state' in workout:
            if workout['state'] != "DELETED" and workout['state'] != "COMPLETED_DELETING_SERVERS":
                if 'hourly_cost' in workout and 'runtime_counter' in workout:
                    if workout['hourly_cost'] and workout['runtime_counter']:
                        estimated_cost = (float(workout['hourly_cost']) / 3600) * float(workout['runtime_counter'])
                        workout['estimated_cost'] = format(estimated_cost, '.2f')
                workout['id'] = workout.key.name
                active_workouts.append(workout)
    return json.dumps(active_workouts)


@admin_api.route('/iot_devices/list', methods=['GET'])
def get_iot_devices():
    if request.method == 'GET':
        device_list = []
        devices_query = ds_client.query(kind=IotManager().kind).fetch()

        if devices_query:
            for device in devices_query:
                device_list.append(json.loads(json.dumps(device), parse_int=str))
            print(device_list)
            return json.dumps({'devices': device_list, 'status': 200})
        else:
            return {'status': 404}


@admin_api.route('/iot_device/register', methods=['POST'])
def register_iot_device():
    """
    Used to register, update, and delete IoT devices on current project

    """
    manager = IotManager()
    if request.method == 'POST':
        request_data = request.form.to_dict()
        ssh_key = request_data['register_device_ssh']
        device_id = request_data['register_device_id']
        action = manager.register_new_iot_device(device_id=device_id, certificate=ssh_key)
        return json.dumps(action)


@admin_api.route('/iot_device/<device_id>/update', methods=['POST'])
def update_iot_device(device_id):
    """
        Requests to this route either updates existing device registry
        or device datastore object
    """
    manager = IotManager()
    device_obj = {}

    if request.method == 'POST':
        request_form = request.form.to_dict()
        print(request_form)
        device_status = request_form['device_status']

        # Prepare device object and forward on to manager class
        device_obj['status'] = device_status
        device_obj['comments'] = request_form['comments']
        if device_status == manager.DeviceStates.READY:
            # Device is checked and ready to be used again
            action = manager.update_device_entity(device_id=device_id, data=device_obj)
        elif device_status == manager.DeviceStates.SENT:
            # Device was sent out to a student
            device_obj['current_student'] = {
                'name': request_form['student_name'],
                'address': request_form['student_address'],
                'tracking_number': request_form['tracking_num']
            }
            date_sent = request_form['date_sent']
            device_obj['date_sent'] = datetime.datetime.strptime(date_sent, "%Y-%m-%d").timestamp()
            action = manager.update_device_entity(device_id=device_id, data=device_obj)
        elif device_status == manager.DeviceStates.CHECK:
            # Device needs to be checked before being sent out again
            date_recv = request_form['date_recv']
            device_obj['date_received'] = datetime.datetime.strptime(date_recv, "%Y-%m-%d").timestamp()
            action = manager.update_device_entity(device_id=device_id, data=device_obj)
        elif device_status == manager.DeviceStates.UPDATE:
            # Update to device SSH keys
            device_ssh = request_form['device_ssh']
            device_obj['certificate'] = device_ssh
            action = manager.update_device_entity(device_id=device_id, data=device_obj)

        return json.dumps(action)


@admin_api.route('/iot_device/<device_id>/delete', methods=['POST'])
def delete_iot_device(device_id):
    manager = IotManager()
    if request.method == 'POST':
        request_json = request.get_json()
        action = manager.delete_iot_device(request_json['device_id'])
        return json.dumps(action)


@admin_api.route('iot_device/<device_id>/send_command', methods=['POST'])
def send_command(device_id):
    manager = IotManager()
    if request.method == 'POST':
        action = manager.send_command(device_id=device_id)
        return json.dumps(action)


@admin_api.route("/admin_scripts", methods=['POST'])
def admin_scripts():
    if request.method == 'POST':
        request_data = request.form.to_dict()
        command_dict = {}
        command_dict["params"] = {}
        for key, value in request_data.items():
            if key == 'function_name':
                command_dict["function_name"] = value.lower()
            else:
                command_dict["params"].update({key: value})

        pub_admin_scripts(json.dumps(command_dict))
        return json.dumps({str(command_dict['function_name']): 'Command Sent'})


@admin_api.route('/update_logo', methods=['POST'])
def update_logo():
    if request.method == "POST":
        data = request.files['custom_logo']
        store_custom_logo(data)
        g_logger = log_client.logger('admin-app')
        g_logger.log_struct(
            {
                "message": "Updating logo image"
            }, severity=LOG_LEVELS.INFO
        )
    return redirect('/admin/home')


@admin_api.route('/update_workout_list', methods=["POST"])
def update_workout_list():
    if request.method == 'POST':
        if 'new_workout_name' and 'new_workout_display' in request.form:
            admin_info = ds_client.get(ds_client.key('cybergym-admin-info', 'cybergym'))
            workout_list = admin_info['workout_list']
            if not any(workout['workout_name'] == request.form['new_workout_name'] for workout in workout_list):
                new_workout_info = {
                    'workout_name': request.form['new_workout_name'],
                    'workout_display_name': request.form['new_workout_display']
                }
                workout_list.append(new_workout_info)
                ds_client.put(admin_info)
                return 'Complete'
            else:
                return 'Failed'
        else:
            return 'Failed'


@admin_api.route('/server_management/<workout_id>', methods=['POST'])
def admin_server_management(workout_id):
    if request.method == 'POST':
        data = request.json
        if 'action' in data:
            g_logger = log_client.logger('admin-app')
            g_logger.log_struct(
                {
                    "message": "{} action called for server {}".format(data['action'], data['server_name'])
                }, severity=LOG_LEVELS.INFO
            )
            pub_manage_server(data['server_name'], data['action'])
    return 'True'


@admin_api.route('/change_workout_state', methods=['POST'])
def change_workout_state():
    if request.method == 'POST':
        request_data = request.get_json(force=True)
        response = {}
        response['workout_id'] = request_data['workout_id']
        response['new_state'] = request_data['new_state']

        workout = ds_client.get(ds_client.key('cybergym-workout', request_data['workout_id']))
        if 'state' in workout:
            previous_state = workout['state']
        workout['state'] = request_data['new_state']
        g_logger = log_client.logger('admin-app')
        g_logger.log_struct(
            {
                "message": "Workout {} state override: {} to {}".format(request_data['workout_id'], previous_state, request_data['new_state']),
                "previous_state": str(previous_state),
                "new_state": str(request_data['new_state']),
                "workout": str(request_data['workout_id'])
            }, severity=LOG_LEVELS.INFO
        )
        ds_client.put(workout)
        return json.dumps(response)


@admin_api.route('/change_workout_expiration', methods=['POST'])
def change_workout_expiration():
    if request.method == "POST":
        request_data = request.get_json(force=True)
        if 'workout_id' in request_data:
            workout = ds_client.get(ds_client.key('cybergym-workout', request_data['workout_id']))
            workout['expiration'] = request_data['new_expiration']
            ds_client.put(workout)
        return json.dumps(str("Test"))


@admin_api.route('/create_workout_spec', methods=['POST'])
def create_workout_spec():
    if request.method == 'POST':
        request_data = request.get_json(force=True)

        yaml_string = YamlFunctions().generate_yaml_content(request_data)
        return json.dumps(yaml_string)


@admin_api.route('/save_workout_spec', methods=['POST'])
def save_workout_spec():
    if request.method == 'POST':
        request_data = request.get_json(force=True)
        YamlFunctions().save_yaml_file(request_data)
        response = {}
        response['completed'] = True
        admin_info = ds_client.get(ds_client.key('cybergym-admin-info', 'cybergym'))
        workout_entry = str(request_data['workout']['name'])
        if 'workout_list' not in admin_info:
            admin_info['workout_list'] = []
        g_logger = log_client.logger('admin-app')
        g_logger.log_struct(
            {
                "message": "Created new workout specification",
                "new_workout_type": workout_entry
            }, severity=LOG_LEVELS.INFO
        )
        admin_info['workout_list'].append(workout_entry.replace(" ", "").lower())
        ds_client.put(admin_info)

        return json.dumps(response)


@admin_api.route('/instance_info', methods=["POST"])
def instance_info():
    if request.method == "POST":
        data = request.get_json()
        if 'instance' in data:
            instance_query = compute.instances().list(project=project, zone=zone, filter=("name:"+data['instance'])).execute()
            instance_info = {}
            instance_details = instance_query['items'][0]
            nics = []
            if 'networkInterfaces' in instance_details:
                for nic in instance_details['networkInterfaces']:
                    nic_info = {}
                    if 'networkIP' in nic:
                        nic_info['ip'] = nic['networkIP']
                    nics.append(nic_info)
            instance_info['nics'] = nics

        return json.dumps(instance_info)


@admin_api.route('/upload_instructions', methods=['POST'])
def upload_instructions():
    if request.method == 'POST':
        if 'teacher_instruction_file' in request.files:
            teacher_instruction_file = request.files['teacher_instruction_file']
            upload_instruction_file(teacher_instruction_file, workout_globals.teacher_instruction_folder, teacher_instruction_file.filename)
        if 'student_instruction_file' in request.files:
            student_instruction_file = request.files['student_instruction_file']
            upload_instruction_file(student_instruction_file, workout_globals.student_instruction_folder, student_instruction_file.filename)
        return json.dumps({"Upload": True})
