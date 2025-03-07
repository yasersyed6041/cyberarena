// Global Vars
var json_headers = {
    'Accept': 'application/json',
    'Content-Type': 'application/json; charset=UTF-8'
}
function getEscapeRoomState (build_id, ts=300000, started=true){
    // Checks current escape_room status every 5 minutes and updates
    // the page as needed
    const URL = '/api/escape-room/team/' + build_id + '?status=true';
    setInterval(function() {
        $.ajax({
            url: URL,
            type: 'get',
            success: function (data){
                let toJson = JSON.parse(data);
                if (Number(toJson['data']['escape_room']['start_time']) > 0){
                    if (started) {
                        checkPuzzles(toJson['status'], toJson['data']);
                    } else {
                        window.location.reload();
                    }
                } else {
                    console.log('...Not started');
                }
            }
        })
    }, ts);
}
function checkEscapeRoom(build_id, form_id, puzzle_idx, ea) {
    showCurrentPuzzle(puzzle_idx);
    const URL = '/api/escape-room/team/' + build_id;
    let puzzle_form = document.getElementById(form_id);
    let question_id = puzzle_form.querySelector('input[name="question_id"]').value;
    let response = puzzle_form.querySelector('input[name="response"]').value;
    let send_data = JSON.stringify({'build_id': build_id, 'response': response, 'question_id': question_id, 'ea': ea});
    fetch(URL, {
        method: "PUT",
        headers: {'Content-Type': 'application/json'},
        body: send_data
    })
        .then((response) => response.json())
        .then(data=>checkPuzzles(data['status'], data['data'], puzzle_idx, question_id));
}
function checkPuzzles(code, responseData, puzzle_idx, question_id){
    if (code === 200){
        console.log('Updating Room Status ...');
        let room = responseData['escape_room'];
        let number_correct = room['number_correct'];
        let puzzle_count = room['puzzle_count'];
        if (number_correct !== puzzle_count){
            for (let i = 0; i < room['puzzles'].length; i++){
                let puzzle = room['puzzles'][i];
                if (puzzle['correct'] === true && puzzle['id'] === question_id){
                    let card = document.getElementById('puzzle-' + puzzle_idx + '-status').innerText = 'Complete!';
                    let reveal = document.getElementById(puzzle['id'] + '-reveal');
                    reveal.innerText = puzzle['reveal'];
                }
            }
        } else {
            if (question_id !== room['id'])
                window.location.reload();
            else {
                if (room['complete'] === true){
                    window.location.reload();
                }
            }
        }
    }
}
function showCurrentPuzzle(puzzle_idx) {
     $('#currentPuzzle' + puzzle_idx).modal('toggle');
}
function showCurrentQuestion(question_idx){
    $('#currentQuestion' + question_idx).modal('toggle');
}
function collapseDiv(){
    let coll = document.getElementsByClassName("collapseBtn");
    for (let i = 0; i < coll.length; i++) {
        coll[i].addEventListener("click", function() {
            this.classList.toggle("collapse-active");
            addClass(this);
            let content = this.nextElementSibling;
            if (content.style.display === "block") {
                content.style.display = "none";
            } else {
                content.style.display = "block";
            }
        });
    }
    function addClass(parent){
        let iconSpan = parent.querySelectorAll(':scope > span')[0];
        // Add the element based on parent element class
        if (parent.classList.contains('collapse-active')){
            iconSpan.innerHTML = '<i class="fa fa-minus" aria-hidden="true"></i>';
        } else {
            iconSpan.innerHTML = '<i class="fa fa-angle-down" aria-hidden="true"></i>';
        }
    }
}
function checkQuestion(questionID, build_id, url, puzzle_idx, check_auto){
    showCurrentQuestion(puzzle_idx);
    let question_form = document.getElementById(questionID + 'Form');
    let response = question_form.querySelector('input[name="response"]').value;
    let parent_id = question_form.querySelector('input[name="parent_id"]').value;
    let send_data = JSON.stringify({'build_id': build_id, 'response': response, 'question_id': questionID, 'check_auto': check_auto});
    fetch(url, {
        method: 'PUT',
        headers: json_headers,
        body: send_data
    })
        .then((response) => response.json())
        .then(data=>updateQuestions(data['status'], data['data']));
}
function updateQuestions(code, responseData){
    // updates all question fields upon request
    if (code === 200){
        for (let i = 0; i < responseData['questions'].length; i++){
            let question = responseData['questions'][i];
            let item = document.getElementById(question['id'] + 'Status');
            if (question['complete'] === true){
                item.innerText = 'Complete!';
            } else if (question['complete'] === false){
                item.innerText = 'Incomplete';
            }
        }
    }
}