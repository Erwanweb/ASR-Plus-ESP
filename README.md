install :

cd ~/domoticz/plugins

mkdir ASRPlusESP

sudo apt-get update

sudo apt-get install git

git clone https://github.com/Erwanweb/ASR-Plus-ESP.git ASRPlusESP

cd ASRPlusESP

sudo chmod +x plugin.py

sudo /etc/init.d/domoticz.sh restart

Upgrade :

cd ~/domoticz/plugins/ASRPlusESP

git reset --hard

git pull --force

sudo chmod +x plugin.py

sudo /etc/init.d/domoticz.sh restart
