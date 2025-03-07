# Certbot Lab Manual
Public key cryptography is a fundamental aspect of most security operations centers, and it often involves installing cryptographic credentials and creating digital certificates. This practical exercise guides you step-by-step on how to secure web server communications using public key infrastructure, with the digital certificates validated by the Electronic Frontier Foundation (EFF).

EFF utilizes a tool named Certbot, which simplifies the process of obtaining and installing web certificates. Certbot is designed to make these certificates not only accessible but also free, thereby encouraging more widespread use of secure protocols on the internet.

To gain a more in-depth understanding of Certbot, how it works, and how it facilitates the process of web security, you can visit the official EFF page dedicated to Certbot at this URL: https://certbot.eff.org/pages/about.

## Instructions

Follow these instructions to install your certificate through the Let's Encrypt certbot tool. Connect through SSH to your web server either through the web application or using a local SSH client. Login using the following credentials:
```
username: cyberarena
password: Let's workout!
```

> **TIP:** To copy and paste between here and your lab environment, you must click on the lab in your browser and type Ctrl-Alt-Shift. This will open the clipboard shared between your lab and your computer. You can paste inside the clipboard textbox. Then, when you click into the lab, you will be able to paste the contents of the clipboard.

### Prepare the website
You already have the Apache webserver installed on your web server, but you still need to prepare the webserver to use your DNS. prepare the web server to server from your designated domain. Your lab has a specific DNS name for the webserver using your lab ID.
1. Create a directory for your website:
```
sudo mkdir -p /var/www/<LAB-ID>-myweb.trojan-cybergym.org
```

2. Create a new virtual host configuration for your website.
```
sudo vim /etc/httpd/conf.d/<LAB-ID>-myweb.trojan-cybergym.org.conf
```

Then, click i to insert the following text into the new file:
```
<VirtualHost *:80>
    ServerName <LAB-ID>-myweb.trojan-cybergym.org
    ServerAlias *.<LAB-ID>-myweb.trojan-cybergym.org
    DocumentRoot /var/www/<LAB-ID>-myweb.trojan-cybergym.org
</VirtualHost>
```

3. Save the file by typing :wq
Reload the web server using the following commands:
```
sudo systemctl reload httpd
```

### Install certbot
```
sudo snap install core
sudo snap install --classic certbot
sudo ln -s /snap/bin/certbot /usr/bin/certbot
```

### Install the Certificate
Initiate the certbot installation:
```
sudo certbot --apache 
```
Enter your email address when prompted, and when asked for your domain name, use <LAB-ID>-myweb.trojan-cybergym.org.
