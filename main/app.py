import json
import requests
from flask import Flask, jsonify, redirect, render_template, request, session
from utilities.reset_workout import reset_workout
from utilities.stop_workout import stop_workout
from utilities.arena_authorizer import ArenaAuthorizer
from utilities.datastore_functions import *
from utilities.globals import auth_config, cloud_log, log_client, logger, LOG_LEVELS, LogIDs, \
    post_endpoint, workout_token
from utilities.pubsub_functions import *

# App Blueprints
from admin_app.routes import admin_app
from student_app.routes import student_app
from teacher_app.routes import teacher_app

# --------------------------- FLASK APP --------------------------
app = Flask(__name__)
app.register_blueprint(admin_app)
app.register_blueprint(student_app)
app.register_blueprint(teacher_app)
app.config['SECRET_KEY'] = 'XqLx4yk8ZW9uukSCXIGBm0RFFJKKyDDm'
app.jinja_env.globals['project'] = project


# Default route
@app.route('/')
def default_route():
    return render_template('login.html', auth_config=auth_config)


@app.route('/home/')
def home():
    if 'user_groups' in session:
        if 'students' in session['user_groups']:
            return redirect("/student/home")
        else:
            return redirect("/teacher/home")
    else:
        return redirect('/unauthorized')


@app.route("/login", methods=['GET', 'POST'])
def login():         
    if request.method == 'POST':
        user_data = request.get_json(force=True)
        if 'user_email' in user_data:
            arena_auth = ArenaAuthorizer()
            user_groups = arena_auth.get_user_groups(user_data['user_email'])
            if user_groups:
                session['user_email'] = user_data['user_email']
                session['user_groups'] = user_groups
                cloud_log(LogIDs.MAIN_APP, f"User {user_data['user_email']} logged in", LOG_LEVELS.INFO)
                return json.dumps({"redirect": "/home"})
        return json.dumps({'redirect': '/unauthorized'})
    return render_template('login.html', auth_config=auth_config, error_resp='403')


@app.route('/logout', methods=['POST'])
def logout():
    if request.method == 'POST':
        print(request.get_json(force=True))
        session.clear()
        return json.dumps({'logged_out': True})


@app.route('/workout_state/<workout_id>', methods=["POST"])
def check_workout_state(workout_id):
    workout = ds_client.get(ds_client.key('cybergym-workout', workout_id))
    if (request.method == "POST"):
        if workout:
            if 'state' in workout:
                return workout['state']
            else:
                return "RUNNING"
        else:
            return "NOT FOUND"


@app.route('/build_workout', methods=['POST'])
def build_workout():
    """
    Initiates a cloud build for the specified workout ID
    @return: None
    """
    data = request.get_json(force=True)
    workout_id = data.get('workout_id', None)
    if not workout_id:
        return redirect(404)

    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(project, workout_globals.ps_build_workout_topic)
    publisher.publish(topic_path, data=b'Cyber Gym Workout', workout_id=workout_id)

    cloud_log(workout_id, f"Student initiated cloud build for workout {workout_id}", LOG_LEVELS.INFO)
    return 'Workout Built'


# Called by start workout buttons on landing pages
@app.route('/start_vm', methods=['GET', 'POST'])
def start_vm():
    if (request.method == 'POST'):
        data = request.get_json(force=True)
        workout_id = None
        run_hours = None
        if 'workout_id' in data:
            workout_id = data['workout_id']
        if 'time' in data:
            run_hours = data['time']
            
        workout = ds_client.get(ds_client.key('cybergym-workout', workout_id))
        if run_hours:
            workout['run_hours'] = min(int(run_hours), workout_globals.MAX_RUN_HOURS)
        else:
            workout['run_hours'] = 2

        ds_client.put(workout)
        g_logger = log_client.logger('student-app')
        g_logger.log_struct(
            {
                "message": "Workout {} started by student".format(workout_id),
                "workout": str(workout_id),
                "runtime": str(workout['run_hours'])
            }, severity=LOG_LEVELS.INFO
        )
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
        g_logger = log_client.logger('student-app')
        g_logger.log_struct(
            {
                "message": "Workout {} stopped by student".format(workout_id),
                "workout": str(workout_id)
            }, severity=LOG_LEVELS.INFO
        )
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
        if workout_id:
            g_logger = log_client.logger(str(workout_id))
            g_logger.log_text(str('Resetting workout ' + workout_id))
        try:
            reset_workout(workout_id)
        except:
            compute = workout_globals.refresh_api()
            reset_workout(workout_id)
        g_logger = log_client.logger('student-app')
        g_logger.log_struct(
            {
                "message": "Workout {} reset by student".format(workout_id),
                "workout": str(workout_id)
            }, severity=LOG_LEVELS.INFO
        )
        return redirect("/landing/%s" % (workout_id))


@app.route('/nuke_workout/<workout_id>', methods=['POST'])
def nuke_workout(workout_id):
    """
    Tied to the nuke button, this sends a pub_sub message to the cloud function for deleting and rebuilding
    the workout tied to workout_id
    """
    workout = ds_client.get(ds_client.key('cybergym-workout', workout_id))
    if workout:
        pub_nuke_workout(workout_id)
    return json.dumps({"completed": True})


@app.route('/check_user_level', methods=['POST'])
def check_user_level():
    if (request.method == 'POST'):
        user_info = request.get_json(force=True)
        user_email = user_info.get('user_email', None)
        arena_auth = ArenaAuthorizer()
        user_groups = arena_auth.get_user_groups(user_email)
        authorized = admin = False
        if user_groups:
            authorized = True
            admin = True if ArenaAuthorizer.UserGroups.ADMINS in user_groups else False
            student = True if ArenaAuthorizer.UserGroups.STUDENTS in user_groups else False
            response = {
                'authorized': authorized,
                'admin': admin,
                'student': student
            }
            return json.dumps(response)
        else:
            return json.dumps({
                'authorized': False,
                'admin': False,
                'student': False
            })


@app.route('/leave_comment', methods=['POST'])
def leave_comment():
    if(request.method == 'POST'):
        comment_email = request.form['comment_email']
        comment_subject = request.form['comment_subject']
        comment_text = request.form['comment_text']
        store_comment(comment_email, comment_subject, comment_text)

        return redirect('/')


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


@app.route('/arena-functions', methods=['POST'])
def arena_functions():
    """
    Used for interacting between workouts in an arena build. The request data includes the following variables:
    workout_id - The workout on which to perform a given action
    action - The action to perform on the given workout (e.g., deduct-points)
    """
    if request.method == 'POST':
        arena_data = request.get_json(force=True)
        workout_id = arena_data['workout_id'] if 'workout_id' in arena_data else None
        action = arena_data['action'] if 'action' in arena_data else None

        if action == 'deduct-points' and workout_id:
            workout = ds_client.get(ds_client.key('cybergym-workout', workout_id))
            if 'points_deducted' not in workout:
                if 'points' in workout:
                    workout['points'] -= 100
                else:
                    workout['points'] = -100
                workout['points_deducted'] = True
                return_data = {"msg": f"You deducted 100 points from {workout['student_name']}"}
            else:
                return_data = {"msg": f"Sorry...someone else beat you to it."}
            ds_client.put(workout)

        else:
            return_data = {"msg": f"Invalid action called: {action} for {workout_id}"}

        return jsonify(return_data), 200


@app.route('/arena-scoreboard/<arena_id>', methods=['GET', 'POST'])
def arena_scoreboard(arena_id):
    arena_build = ds_client.get(ds_client.key('cybergym-unit', str(arena_id)))

    team_info = {}
    flag_info = {}
    arena_type = ""

    teams = arena_build['teams'] if 'teams' in arena_build else None
    for team in teams:
        team_name = str(team)
        workout_query = ds_client.query(kind='cybergym-workout')
        workout_query.add_filter('unit_id', '=', str(arena_id))
        workout_query.add_filter('team', '=', team_name)
        team_workouts = list(workout_query.fetch())
        team_info[team_name] = {}
        team_info[team_name]['members'] = []

        for workout in team_workouts:
            if len(flag_info.values()) == 0:
                flag_info = workout['assessment']
                arena_type = workout['type']
            team_info[team_name]['found_flags'] = []
            submitted_flags = []
            for flag in flag_info['questions']:
                if 'submitted_answers' in workout:
                    for submitted_answer in workout['submitted_answers']:
                        # submitted_flags.append(submitted_answer['answer'])
                        submitted_flags.append({
                            'answer': submitted_answer['answer'],
                            'timestamp': submitted_answer['timestamp'],
                            'first': submitted_answer['first'] if 'first' in submitted_answer else False
                        })
                if next((item for item in submitted_flags if item['answer'] == flag['answer']), False):
                    team_info[team_name]['found_flags'].append(next(item for item in submitted_flags if item['answer'] == flag['answer']))
                else:
                    team_info[team_name]['found_flags'].append(0)
            team_info[team_name]['members'].append(workout.key.name)

            team_info[team_name]['points'] = workout['points'] if 'points' in workout else 0
        if not team_info[team_name]['members']:
            team_info[team_name]['points'] = 0
    team_info = sorted(team_info.items(), key = lambda i: i[1]['points'], reverse=True)
    
    return render_template('arena_scoreboard.html', arena_info=arena_build, team_info=team_info, arena_type=arena_type, flag_info=flag_info)


@app.route('/faq', methods=['GET'])
def faq():
    return render_template('faq.html')


@app.route('/cyberattack_faq', methods=['GET'])
def cyberattack_faq():
    return render_template('cyberattack_faq.html')


@app.route('/ransomware_faq', methods=['GET'])
def ransomware_faq():
    return render_template('ransomware_faq.html')


@app.route('/dos_faq', methods=['GET'])
def dos_faq():
    return render_template('dos_faq.html')


@app.route('/johnnyhash_faq', methods=['GET'])
def johnnyhash_faq():
    return render_template('johnnyhash_faq.html')


@app.route('/johnnycipher_faq', methods=['GET'])
def johnnycipher_faq():
    return render_template('johnnycipher_faq.html')


@app.route('/mobileforensics_faq', methods=['GET'])
def mobileforensics_faq():
    return render_template('mobileforensics_faq.html')


@app.route('/trust_faq', methods=['GET'])
def trust_faq():
    return render_template('trust_faq.html')


@app.route('/nessus_faq', methods=['GET'])
def nessus_faq():
    return render_template('nessus_faq.html')


@app.route('/bufferoverflow_faq', methods=['GET'])
def bufferoverflow_faq():
    return render_template('bufferoverflow_faq.html')


@app.route('/publicprivate_faq', methods=['GET'])
def publicprivate_faq():
    return render_template('publicprivate_faq.html')


@app.route('/wireshark_faq', methods=['GET'])
def wireshark_faq():
    return render_template('wireshark_faq.html')


@app.route('/2fa_faq', methods=['GET'])
def twofa_faq():
    return render_template('2fa_faq.html')


@app.route('/access-control_faq', methods=['GET'])
def accesscontrol_faq():
    return render_template('access-control_faq.html')


@app.route('/arena_snake_faq', methods=['GET'])
def arena_snake_faq():
    return render_template('arena_snake_faq.html')


@app.route('/hiddennode_faq', methods=['GET'])
def hiddennode_faq():
    return render_template('hiddennode_faq.html')


@app.route('/inspect_faq', methods=['GET'])
def inspect_faq():
    return render_template('inspect_faq.html')


@app.route('/kersplunk_faq', methods=['GET'])
def kersplunk_faq():
    return render_template('kersplunk_faq.html')


@app.route('/missionpermissions2_faq', methods=['GET'])
def missionpermissions2_faq():
    return render_template('missionpermissions2_faq.html')


@app.route('/password-policy_faq', methods=['GET'])
def passwordpolicy_faq():
    return render_template('password-policy_faq.html')


@app.route('/phishing_faq', methods=['GET'])
def phishing_faq():
    return render_template('phishing_faq.html')


@app.route('/reversus_faq', methods=['GET'])
def reversus_faq():
    return render_template('reversus_faq.html')


@app.route('/shodan_faq', methods=['GET'])
def shodan_faq():
    return render_template('shodan_faq.html')


@app.route('/sql_injection_faq', methods=['GET'])
def sql_injection_faq():
    return render_template('sql_injection_faq.html')


@app.route('/xss_faq', methods=['GET'])
def xss_faq():
    return render_template('xss_faq.html')


# For debugging of pub/sub
@app.route('/publish', methods=['GET', 'POST'])
def publish():
    if (request.method == 'POST'):
        workout_id = request.form['workout_id']
        msg = {"token": workout_token,
               "workout_id": workout_id}
        res = requests.post(post_endpoint, json=msg)
        print(res)
    return redirect("/student/landing/%s" % (workout_id))


@app.route('/unauthorized', methods=['GET', 'POST'])
def unauthorized():
    return render_template("unauthorized.html")


@app.errorhandler(500)
def handle_500(e):
    g_logger = log_client.logger('cybergym-app-errors')
    g_logger.log_struct(
        {
            "error_type": 500,
            "details": str(e),
            "request": str(request)
        }
    )
    return render_template("500.html", error=e), 500


@app.errorhandler(404)
def handle_404(e):
    g_logger = log_client.logger('cybergym-app-errors')
    g_logger.log_struct(
        {
            "error_type": 404,
            "details": str(e),
            "request": str(request)
        }
    )
    return render_template("404.html")


@app.route('/privacy', methods=['GET'])
def privacy():
    return render_template('privacy.html')


if __name__ == '__main__':
     app.run(debug=True, host='0.0.0.0', port=8080, threaded=True)
