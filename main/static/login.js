function configureFirebaseLogin() {
      
    //Used in the initial login page 
    firebase.auth().onAuthStateChanged(function(user) {
      if (user) {
        var name = user.displayName;
        
        /* If the provider gives a display name, use the name for the
        personal welcome message. Otherwise, use the user's email. */
        var welcomeName = user.email;

        user.getIdToken().then(function(idToken) {
          userIdToken = idToken;
          user_name = name;
          user_email = welcomeName;
          //alert("Logged in");
          
          $('#user').text(welcomeName);
          $('#logged-in').show();

        });

      } else {
        $('#logged-in').hide();
        $('#login_container').show();

      }
    });
    // [END gae_python_state_change]

}

function configureFirebaseLoginWidget() {
    var uiConfig = {
        callbacks: {
          signInSuccessWithAuthResult: function(authResult, redirectUrl){
            console.log(authResult.user);
            var data = {user_email: authResult.user.email};
            $.ajax({
              type: "POST",
              url: "/login",
              dataType: "json",
              contentType: "application/json;charset=UTF-8;",
              data: JSON.stringify(data),
              success: function(result){
                location.href=result['redirect'];
              },
              error: function(e){
                console.log(e);
              }
            })
            return false;
          }
        },
        'signInFlow': 'redirect',
        'signInSuccessUrl': '/home',
        'signInOptions': [
        // Leave the lines as is for the providers you want to offer your users.
          firebase.auth.GoogleAuthProvider.PROVIDER_ID,
          firebase.auth.EmailAuthProvider.PROVIDER_ID
        ],
        // Terms of service url
        // 'tosUrl': '<your-tos-url>',
    };

    var ui = new firebaseui.auth.AuthUI(firebase.auth());
    ui.start('#firebaseui-auth-container', uiConfig);
}

function enable_signout(){
  //Enables signout button after successful login
  var signOutBtn =$('#sign-out');
    signOutBtn.click(function(event) {
      event.preventDefault();
      $.ajax({
        type: "POST",
        url: "/logout",
        success: function(){
          firebase.auth().signOut().then(function() {
        
            console.log("Sign out successful");
            window.location.href = "/login";
          }, function(error) {
            console.log(error);
          });
        }
      });
    });
}

function initApp(authConfig){
  //Initialize firebase app with API key, domain, and GCP project
  firebase.initializeApp(authConfig);
  return new Promise(function(resolve, reject){
    firebase.auth().onAuthStateChanged((user) => {
      if(user){        
        
        //POST to server to check user role
        $.ajax({
          type: "POST",
          url: "/check_user_level",
          data: JSON.stringify({
              "user_email": user.email
          }),
          success: function(data){
            let json = $.parseJSON(data)
            let ret_data = {
              "email": "",
              "admin": "",
              "student": "",
              "display_name": user.displayName
            } 
            if(json['authorized'] == false){
              location.href = "/unauthorized";
            } else{
              ret_data['email'] = user.email;
              if(json['admin'] == true){
                ret_data['admin'] = true;
              }
              if(json['student'] == true){
                ret_data['student'] = true;
              }
            }
            resolve(ret_data);
          }
        })
      }
    })
  })
}