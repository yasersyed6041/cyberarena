import time
import requests

from stop_workout import stop_workout
from reset_workout import reset_workout
from utilities.globals import ds_client, dns_suffix, log_client, workout_token, post_endpoint, auth_config, logger
from utilities.pubsub_functions import *
from utilities.yaml_functions import parse_workout_yaml
from utilities.datastore_functions import process_workout_yaml, retrieve_student_uploads, get_custom_logo, \
    get_custom_base, store_custom_logo, store_custom_base, get_unit_workouts
from utilities.assessment_functions import get_assessment_questions, process_assessment
from flask import Flask, render_template, redirect, request
from forms import CreateWorkoutForm
import json
# --------------------------- FLASK APP --------------------------

app = Flask(__name__)

app.config['SECRET_KEY'] = 'XqLx4yk8ZW9uukSCXIGBm0RFFJKKyDDm'
app.jinja_env.globals['CUSTOM_LOGO_LOCATION'] = get_custom_logo()
app.jinja_env.globals['BASE_TEMPLATE'] = get_custom_base()

# TODO: add something at default route to direct users to correct workout?
# Default route
@app.route('/')
def default_route():
    return render_template('login.html', auth_config=auth_config)

    

# Workout build route
@app.route('/<workout_type>', methods=['GET', 'POST'])
def index(workout_type):
    logger.info('Request for workout type %s' % workout_type)
    form = CreateWorkoutForm()
    if form.validate_on_submit():
        yaml_string = parse_workout_yaml(workout_type)
        unit_id, build_type = process_workout_yaml(yaml_string, workout_type, form.unit.data,
                                                     form.team.data, form.length.data, form.email.data)

        if unit_id == False:
            return render_template('no_workout.html')
        elif build_type == 'compute':
            pub_build_request_msg(unit_id=unit_id, topic_name=workout_globals.ps_build_workout_topic)
            print("workout building")
            url = '/workout_list/%s' % (unit_id)
            return redirect(url)
        elif build_type == 'arena':

            pub_build_request_msg(unit_id=unit_id, topic_name=workout_globals.ps_build_arena_topic)
            url = '/arena_list/%s' % (unit_id)
            return redirect(url)

    return render_template('main_page.html', form=form, workout_type=workout_type, auth_config=auth_config)


# Student landing page route. Displays information and links for an individual workout
@app.route('/landing/<workout_id>', methods=['GET', 'POST'])
def landing_page(workout_id):
    workout = ds_client.get(ds_client.key('cybergym-workout', workout_id))
    unit = ds_client.get(ds_client.key('cybergym-unit', workout['unit_id']))
    retrieve_student_uploads(workout_id)
    if (workout):
        expiration = None
        if 'expiration' in workout:
            expiration = time.strftime('%d %B %Y', (
                time.localtime((int(workout['expiration']) * 60 * 60 * 24) + int(workout['timestamp']))))
        shutoff = None
        if 'run_hours' in workout:
            run_hours = int(workout['run_hours'])
            if run_hours == 0:
                shutoff = "expired"
            else:
                shutoff = time.strftime('%d %B %Y at %I:%M %p',
                                    (time.localtime((int(workout['run_hours']) * 60 * 60) + int(workout['start_time']))))

        guac_path = None
        if unit['build_type'] == 'container':
            guac_path = unit['workout_url_path']

        student_instructions_url = None
        if 'student_instructions_url' in workout:
            student_instructions_url = workout['student_instructions_url']

        teacher_instructions_url = None
        if 'teacher_instructions_url' in unit:
            teacher_instructions_url = unit['teacher_instructions_url']

        assessment = assessment_type = None
        if 'assessment' in workout and workout['assessment']:
            assessment, assessment_type = get_assessment_questions(workout)

        workout_state = None
        if 'state' in workout:
            workout_state = workout['state']

        workout_user = None
        if 'workout_user' in workout:
            workout_user = workout['workout_user']
        else:
            workout_user = 'container'
        workout_password = None
        if 'workout_password' in workout:
            workout_password = workout['workout_password']



        if(request.method == "POST"):
            uploaded_files, assessment_answers, percentage_correct = process_assessment(workout, workout_id, request, assessment)

            return render_template('landing_page.html', description=unit['description'], dns_suffix=dns_suffix,
                               guac_path=guac_path, expiration=expiration, student_instructions=student_instructions_url,
                               state=workout_state, shutoff=shutoff, workout_id=workout_id,
                               workout_name=unit['workout_name'], assessment=assessment, assessment_type=assessment_type,
                               score=percentage_correct, guac_user=workout_user, guac_pass=workout_password)

        return render_template('landing_page.html', description=unit['description'], dns_suffix=dns_suffix,
                               guac_path=guac_path, expiration=expiration, student_instructions=student_instructions_url,
                               state=workout_state, shutoff=shutoff, workout_id=workout_id, workout_name=unit['workout_name'], assessment=assessment,
                               assessment_type=assessment_type, guac_user=workout_user, guac_pass=workout_password)
    else:
        return render_template('no_workout.html')

# Instructor landing page. Displays information and links for a unit of workouts
@app.route('/workout_list/<unit_id>', methods=['GET', 'POST'])
def workout_list(unit_id):
    unit = ds_client.get(ds_client.key('cybergym-unit', unit_id))
    build_type = unit['build_type']
    workout_url_path = unit['workout_url_path']
    workout_list = get_unit_workouts(unit_id)
    
    teacher_instructions_url = None
    if 'teacher_instructions_url' in unit:
        teacher_instructions_url = unit['teacher_instructions_url']
    

    #For updating individual workout ready state
    if (request.method=="POST"):
        if build_type == 'arena':
            return json.dumps(unit)
        return json.dumps(workout_list)    
    
    if unit and len(str(workout_list)) > 0:
        return render_template('workout_list.html', build_type=build_type, workout_url_path=workout_url_path,
                               workout_list=workout_list, unit_id=unit_id,
                               description=unit['description'], teacher_instructions=teacher_instructions_url)
    else:
        return render_template('no_workout.html')


@app.route('/arena_list/<unit_id>', methods=['GET', 'POST'])
def arena_list(unit_id):
    unit = ds_client.get(ds_client.key('cybergym-unit', unit_id))
    build_type = unit['build_type']
    workout_url_path = unit['workout_url_path']
    workout_list = get_unit_workouts(unit_id)
    
    teacher_instructions_url = None
    if 'teacher_instructions_url' in unit:
        teacher_instructions_url = unit['teacher_instructions_url']
    
    student_instructions_url = None
    if 'student_instructions_url' in unit:
        student_instructions_url = unit['student_instructions_url']

    start_time = None
    if'start_time' in unit:
        start_time = unit['start_time']
        # start_time = time.gmtime(start_time)
    unit_teams = None
    if 'teams' in unit:
        unit_teams = unit['teams']
    if (request.method=="POST"):
        return json.dumps(unit)

    if unit:
        return render_template('arena_list.html', unit_teams=unit_teams, teacher_instructions=teacher_instructions_url, workout_list=workout_list,
                            student_instructions=student_instructions_url, description=unit['description'], unit_id=unit_id, start_time=start_time)


@app.route('/arena_landing/<workout_id>', methods=['GET', 'POST'])
def arena_landing(workout_id):
    workout = ds_client.get(ds_client.key('cybergym-workout', workout_id))
    unit = ds_client.get(ds_client.key('cybergym-unit', workout['unit_id']))
    
    student_instructions_url = None
    if 'student_instructions_url' in workout:
        student_instructions_url = workout['student_instructions_url']

    assessment = guac_user = guac_pass = flags_found = None

    if 'workout_user' in workout:
        guac_user = workout['workout_user']
    if 'workout_password' in workout:
        guac_pass = workout['workout_password']
    if 'assessment' in workout:
        try:
            assessment, assessment_type = get_assessment_questions(workout)
        except TypeError:
            print("type errors")

    if(request.method == "POST"):
        return process_assessment(workout, workout_id, request, assessment)
       
    return render_template('arena_landing.html', description=unit['description'], assessment=assessment, running=workout['running'], unit_id=workout['unit_id'], dns_suffix=dns_suffix, 
                        guac_user=guac_user, guac_pass=guac_pass, arena_id=workout_id, student_instructions=student_instructions_url)

@app.route("/login", methods=['GET', 'POST'])
def login():
    return render_template('login.html', auth_config=auth_config)

@app.route('/teacher_home', methods=['GET', 'POST'])
def teacher_home():
    return render_template('teacher_home.html', auth_config=auth_config)


@app.route('/admin', methods=['GET', 'POST'])
def admin_page():
    admin_info = ds_client.get(ds_client.key('cybergym-admin-info', 'cybergym'))

    if request.method == "POST":
        response = {
            'action_completed': 'false'
        }
        data = request.get_json(force=True)
        if data['action'] == 'approve_user':
            if data['user_email'] in admin_info['pending_users']:
                admin_info['authorized_users'].append(data['user_email'])
                admin_info['pending_users'].remove(data['user_email'])
                ds_client.put(admin_info)
                response['action_completed'] = 'true'
        elif data['action'] == 'deny_user':
            if data['user_email'] in admin_info['pending_users']:
                admin_info['pending_users'].remove(data['user_email'])
                ds_client.put(admin_info)
                response['action_completed'] = 'true'
        elif data['action'] == 'promote_user':
            if data['user_email'] in admin_info['authorized_users']:
                admin_info['admins'].append(data['user_email'])
                ds_client.put(admin_info)
                response['action_completed'] = 'true'
        elif data['action'] == 'remove_user':
            if data['user_email'] in admin_info['authorized_users']:
                admin_info['authorized_users'].remove(data['user_email'])
                ds_client.put(admin_info)
                response['action_completed'] = 'true'
        elif data['action'] == 'revoke_access':
            if data['user_email'] in admin_info['admins']:
                admin_info['admins'].remove(data['user_email'])
                ds_client.put(admin_info)
                response['action_completed'] = 'true'
        return json.dumps(response)
        
    return render_template('admin_page.html', auth_config=auth_config, admin_info=admin_info)

@app.route('/update_logo', methods=['POST'])
def update_logo():
    if request.method == "POST":
        data = request.files['custom_logo']
        store_custom_logo(data)
        app.jinja_env.globals['CUSTOM_LOGO_LOCATION'] = get_custom_logo()
    return redirect('/teacher_home')

@app.route('/update_base', methods=['POST'])
def update_base():
    if request.method == "POST":
        data = request.files['custom_base']
        store_custom_base(data)
        app.jinja_env.globals['BASE_TEMPLATE'] = get_custom_base()
    return redirect('/teacher_home')

@app.route('/teacher_info', methods=['GET', 'POST'])
def get_teacher_info():
    if (request.method == "POST"):
        teacher_email = request.get_json()
        unit_list = ds_client.query(kind='cybergym-unit')
        unit_list.add_filter("instructor_id", "=", str(teacher_email['teacher_email']))
        # unit_list.add_filter("resources_deleted", "=", False)
        teacher_units = []

        for unit in list(unit_list.fetch()):
            unit_info = {
                'unit_id': unit.key.name,
                'workout_name': unit['workout_name'],
                'build_type': unit['build_type'],
                'unit_name': unit['unit_name'],
                'timestamp': unit['timestamp']
            }
            teacher_units.append(unit_info)

        teacher_units = sorted(teacher_units, key = lambda i: (i['timestamp']), reverse=True)
    return json.dumps(teacher_units)

@app.route('/workout_state/<workout_id>', methods=["POST"])
def check_workout_state(workout_id):
    workout = ds_client.get(ds_client.key('cybergym-workout', workout_id))
    if (request.method == "POST"):
        return workout['state']

# TODO: add student_firewall_update call after workout starts
# Called by start workout buttons on landing pages
@app.route('/start_vm', methods=['GET', 'POST'])
def start_vm():
    if (request.method == 'POST'):
        data = request.get_json(force=True)
        workout_id = None
        if 'workout_id' in data:
            workout_id = data['workout_id']
        g_logger = log_client.logger(str(workout_id))
        g_logger.log_text(str('Starting workout ' + workout_id))
        workout = ds_client.get(ds_client.key('cybergym-workout', workout_id))
        if 'time' not in request.form:
            workout['run_hours'] = 2
        else:
            workout['run_hours'] = min(int(request.form['time']), workout_globals.MAX_RUN_HOURS)
        # workout['running'] = True
        ds_client.put(workout)

        pub_start_vm(workout_id)
        return 'VM Started'


# Called by stop workout buttons on landing pages
@app.route('/stop_vm', methods=['GET', 'POST'])
def stop_vm():
    if (request.method == 'POST'):
        data = request.get_json(force=True)
        workout_id = None
        if 'workout_id' in data:
            workout_id = data['workout_id']
        g_logger = log_client.logger(str(workout_id))
        g_logger.log_text(str('Stopping workout ' + workout_id))
        try:
            pub_stop_vm(workout_id)
        except:
            compute = workout_globals.refresh_api()
            stop_workout(workout_id)
        # return redirect("/landing/%s" % (workout_id))
        return 'VM Stopped'

# Called by reset workout buttons on landing pages
@app.route('/reset_vm', methods=['GET', 'POST'])
def reset_vm():
    if (request.method == 'POST'):
        data = request.get_json(force=True)
        workout_id = None
        if 'workout_id' in data:
            workout_id = data['workout_id']
        g_logger = log_client.logger(str(workout_id))
        g_logger.log_text(str('Resetting workout ' + workout_id))
        try:
            reset_workout(workout_id)
        except:
            compute = workout_globals.refresh_api()
            reset_workout(workout_id)
        return redirect("/landing/%s" % (workout_id))

# Called by start workouts button on instructor landing. Starts all workouts in a unit.
@app.route('/start_all', methods=['GET', 'POST'])
def start_all():
    if (request.method == 'POST'):
        unit_id = request.form['unit_id']
        workout_list = get_unit_workouts(unit_id)
        t_list = []
        for workout_id in workout_list:
            workout = ds_client.get(ds_client.key('cybergym-workout', workout_id['name']))
            if 'time' not in request.form:
                workout['run_hours'] = 2
            else:
                workout['run_hours'] = min(int(request.form['time']), workout_globals.MAX_RUN_HOURS)
            ds_client.put(workout)

            pub_start_vm(workout_id['name'])

        return redirect("/workout_list/%s" % (unit_id))

@app.route('/start_arena', methods=['GET', 'POST'])
def start_arena():
    if request.method == 'POST':
        unit_id = request.form['unit_id']
        arena_unit = ds_client.get(ds_client.key('cybergym-unit', unit_id))
        if 'time' not in request.form:
            arena_unit['arena']['run_hours'] = 2
        else:
            arena_unit['arena']['run_hours'] = min(int(request.form['time']), workout_globals.MAX_RUN_HOURS)
        ds_client.put(arena_unit)
        start_time = time.gmtime(time.time())
        time_string = str(start_time[3]) + ":" + str(start_time[4]) + ":" + str(start_time[5])
        print(time_string)
        arena_unit['start_time'] = time_string
        ds_client.put(arena_unit)
        pub_start_vm(unit_id, 'start-arena')
    return redirect('/arena_list/%s' % (unit_id))

# Called by stop workouts button on instructor landing page. Stops all workouts
@app.route('/stop_all', methods=['GET', 'POST'])
def stop_all():
    if (request.method == 'POST'):
        unit_id = request.form['unit_id']
        workout_list = get_unit_workouts(unit_id)
        for workout_id in workout_list:
            try:
                stop_workout(workout_id['name'])
            except:
                compute = workout_globals.refresh_api()
                stop_workout(workout_id['name'])
        return redirect("/workout_list/%s" % (unit_id))

# Called by reset workouts button on instructor landing page. Resets all workouts.
@app.route('/reset_all', methods=['GET', 'POST'])
def reset_all():
    if (request.method == 'POST'):
        unit_id = request.form['unit_id']
        workout_list = get_unit_workouts(unit_id)
        for workout_id in workout_list:
            try:
                reset_workout(workout_id['name'])
            except:
                workout_globals.refresh_api()
                reset_workout(workout_id['name'])
        return redirect("/workout_list/%s" % (unit_id))

@app.route('/nuke_workout/<workout_id>', methods=['POST'])
def nuke_workout(workout_id):
    #Get workout information
    workout = ds_client.get(ds_client.key('cybergym-workout', workout_id))
    unit = ds_client.get(ds_client.key('cybergym-unit', workout['unit_id']))
    #Create new workout of same type
    workout_type = workout['type']
    unit_name = unit['unit_name']
    unit_id = workout['unit_id']

    submitted_answers = None
    if 'submitted_answers' in workout:
        submitted_answers = workout['submitted_answers']
    if 'expiration' in unit:
        expiration = unit['expiration']
    else:
        expiration = 0
    instructor_id = workout['user_email']
    yaml_string = parse_workout_yaml(workout_type)
    unit_id, build_type, new_id = process_workout_yaml(yaml_string, workout_type, unit_name,
                                                     1, expiration, instructor_id, unit_id)

    if submitted_answers:
        new_workout = ds_client.get(ds_client.key('cybergym-workout', new_id))
        new_workout['submitted_answers'] = submitted_answers

    unit_id = workout['unit_id']
    #Get new workout information
    response = {
        "unit_id":unit_id,
        "build_type":build_type,
        "workout_id": new_id

    }
    
    if build_type == 'compute':
        pub_build_single_workout(workout_id=new_id, topic_name=workout_globals.ps_build_workout_topic)
    
    if workout_id in unit['workouts']:
        unit['workouts'].remove(workout_id)
    unit['workouts'].append(new_id)
    ds_client.put(unit)

    workout['misfit'] = True
    ds_client.put(workout)
    

    return json.dumps(response)

@app.route('/change_student_name/<workout_id>', methods=["POST"])
def change_student_name(workout_id):
    workout = ds_client.get(ds_client.key("cybergym-workout", workout_id))
    workout['student_name'] = request.values['new_name']
    ds_client.put(workout)
    return workout['student_name']


@app.route('/check_user_level', methods=['POST'])
def check_user_level():
    if (request.method == 'POST'):
        user_info = request.get_json(force=True)
        admin_info = ds_client.get(ds_client.key('cybergym-admin-info', 'cybergym'))
        response = {
            'authorized': False,
            'admin': False
        }
        
        if user_info['user_email']:
            if user_info['user_email'] in admin_info['authorized_users']:
                response['authorized'] = True
                if user_info['user_email'] in admin_info['admins']:
                    response['admin'] = True
            else:
                if user_info['user_email'] not in admin_info['pending_users']:
                    admin_info['pending_users'].append(user_info['user_email'])
                    ds_client.put(admin_info)
        return json.dumps(response)

# Workout completion check. Receives post request from workout and updates workout as complete in datastore.
# Request data in form {'workout_id': workout_id, 'token': token,}
@app.route('/complete', methods=['POST'])
def complete_verification():
    if (request.method == 'POST'):
        workout_request = request.get_json(force=True)

        workout_id = workout_request['workout_id']
        token = workout_request['token']
        workout = ds_client.get(ds_client.key('cybergym-workout', workout_id))

        token_exists = next(item for item in workout['assessment']['questions'] if item['key'] == token)
        token_pos = next((i for i, item in enumerate(workout['assessment']['questions']) if item['key'] == token), None)
        if token_exists:
            logger.info("Completion token matches. Setting the workout question %d to complete." % token_pos)
            workout['assessment']['questions'][token_pos]['complete'] = True
            ds_client.put(workout)
            logger.info('%s workout question %d marked complete.' % (workout_id, token_pos+1))
            return 'OK', 200
        else:
            logger.info("In complete_verification: Completion key %s does NOT exist in assessment dict! Aborting" % token)

# For debugging of pub/sub
@app.route('/publish', methods=['GET', 'POST'])
def publish():
    if (request.method == 'POST'):
        workout_id = request.form['workout_id']
        msg = {"token": workout_token,
               "workout_id": workout_id}
        res = requests.post(post_endpoint, json=msg)
        print(res)
    return redirect("/landing/%s" % (workout_id))

@app.route('/unauthorized', methods=['GET', 'POST'])
def unauthorized():
    return render_template("unauthorized.html")

@app.errorhandler(500)
def handle_500(e):
    print("500 Error detected: " + str(e))
    return render_template("500.html", error=e), 500

@app.errorhandler(404)
def handle_404(e):
    return render_template("404.html")

@app.route('/privacy', methods=['GET'])
def privacy():
    return render_template('privacy.html')


if __name__ == '__main__':
     app.run(debug=True, host='0.0.0.0', port=8080, threaded=True)
