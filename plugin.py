"""
AC Aircon Smart Remote plugin for Domoticz
Author: MrErwan,
Version:    0.0.1: alpha
Version:    0.1.1: beta
"""
"""
<plugin key="AC-ASRplusESP" name="AC Aircon Smart Remote PLUS for ESP" author="MrErwan" version="0.1.1" externallink="https://github.com/Erwanweb/ASR-Plus-ESP.git">
    <description>
        <h2>Aircon Smart Remote</h2><br/>
        Easily implement in Domoticz an full control of air conditoner controled by IR Remote and using ESP<br/>
        <h3>Set-up and Configuration</h3>
    </description>
    <params>
        <param field="Address" label="Domoticz IP Address" width="200px" required="true" default="127.0.0.1"/>
        <param field="Port" label="Port" width="40px" required="true" default="8080"/>
        <param field="Username" label="ESP IP" width="200px" required="true" default=""/>
        <param field="Password" label="AC Brand" width="300px" required="true" default=""/>
        <param field="Mode2" label="Pause sensors (csv list of idx)" width="100px" required="false" default=""/>
        <param field="Mode3" label="Presence Sensors (csv list of idx)" width="100px" required="false" default=""/>
        <param field="Mode4" label="Inside Temperature Sensors (csv list of idx)" width="100px" required="false" default="0"/>
        <param field="Mode5" label="Day/Night Activator, Pause On delay, Pause Off delay, Presence On delay, Presence Off delay (all in minutes), reducted T(in degree), Delta max fanspeed (in in tenth of degre)" width="200px" required="true" default="0,1,1,2,45,3,5"/>
        <param field="Mode6" label="Logging Level" width="200px">
            <options>
                <option label="Normal" value="Normal"  default="true"/>
                <option label="Verbose" value="Verbose"/>
                <option label="Debug - Python Only" value="2"/>
                <option label="Debug - Basic" value="62"/>
                <option label="Debug - Basic+Messages" value="126"/>
                <option label="Debug - Connections Only" value="16"/>
                <option label="Debug - Connections+Queue" value="144"/>
                <option label="Debug - All" value="-1"/>
            </options>
        </param>
    </params>
</plugin>
"""
import Domoticz
#uniquement pour les besoins de cette appli
import getopt, sys
#pour lire le json
import json
import urllib
import urllib.parse as parse
import urllib.request as request
from datetime import datetime, timedelta
import time
import base64
import itertools



class deviceparam:

    def __init__(self,unit,nvalue,svalue):
        self.unit = unit
        self.nvalue = nvalue
        self.svalue = svalue
        self.debug = False




class BasePlugin:
    enabled = True
    powerOn = 0
    SRindex = 1
    runCounter = 0
    httpConnSensorInfo = None
    httpConnControlInfo = None
    httpConnSetControl = None

    def __init__(self):
        self.debug = False
        self.setpoint = 21.0
        self.deltamax = 10  # allowed deltamax from setpoint for high level airfan
        self.ModeAuto = True
        self.ModeManual = False
        self.DayNight = 0
        self.DTDayNight = 0
        self.Night = False
        self.DTpresence = []
        self.Presencemode = False
        self.Presence = False
        self.PresenceTH = False
        self.PresenceTHdelay = datetime.now()
        self.presencechangedtime = datetime.now()
        self.PresenceDetected = False
        self.DTtempo = datetime.now()
        self.presenceondelay = 2  # time between first detection and last detection before turning presence ON
        self.presenceoffdelay = 45  # time between last detection before turning presence OFF
        self.pauseondelay = 1
        self.pauseoffdelay = 1
        self.pause = False
        self.pauserequested = False
        self.pauserequestchangedtime = datetime.now()
        self.reductedsp = 3
        self.InTempSensors = []
        self.intemp = 25.0
        self.nexttemps = datetime.now()
        self.controlinfotime = datetime.now()
        self.controlsettime = datetime.now()
        self.ASRconnected = False
        self.ASRconnexchangedtime = datetime.now()
        self.PLUGINstarteddtime = datetime.now()
        return

    def onStart(self):
        Domoticz.Log("onStart called")
        # setup the appropriate logging level
        try:
            debuglevel = int(Parameters["Mode6"])
        except ValueError:
            debuglevel = 0
            self.loglevel = Parameters["Mode6"]
        if debuglevel != 0:
            self.debug = True
            Domoticz.Debugging(debuglevel)
            DumpConfigToLog()
            self.loglevel = "Verbose"
        else:
            self.debug = False
            Domoticz.Debugging(0)

        # create the child devices if these do not exist yet
        devicecreated = []
        if 1 not in Devices:
            Domoticz.Device(Name="Connexion", Unit=1, TypeName = "Selector Switch",Switchtype = 2, Used =1).Create()
            devicecreated.append(deviceparam(1, 1, "100"))  # default is connected
        if 2 not in Devices:
            Domoticz.Device(Name = "ASR Index",Unit=2,Type = 243,Subtype = 6,).Create()
            devicecreated.append(deviceparam(2,1,"1"))  # default is Index 1
        if 3 not in Devices:
            Domoticz.Device(Name="AC On/Off", Unit=3, TypeName="Switch", Image=9).Create()
            devicecreated.append(deviceparam(3, 1, "100"))  # default is On
        if 4 not in Devices:
            Options = {"LevelActions":"||",
                       "LevelNames":"Off|Auto|Cool|Heat|Dry|Fan",
                       "LevelOffHidden":"true",
                       "SelectorStyle":"0"}
            Domoticz.Device(Name = "AC Manual Mode",Unit=4,TypeName = "Selector Switch",Switchtype = 18,Image = 15,
                            Options = Options,Used = 1).Create()
            devicecreated.append(deviceparam(4,0,"30"))  # default is Heating mode
        if 5 not in Devices:
            Options = {"LevelActions":"||",
                       "LevelNames":"Off|Auto|Low|Mid|High",
                       "LevelOffHidden":"true",
                       "SelectorStyle":"0"}
            Domoticz.Device(Name = "AC Manual Fan Speed",Unit=5,TypeName = "Selector Switch",Switchtype = 18,Image = 15,
                            Options = Options,Used = 1).Create()
            devicecreated.append(deviceparam(5,0,"10"))  # default is Auto mode
        if 6 not in Devices:
            Domoticz.Device(Name = "AC Setpoint",Unit=6,Type = 242,Subtype = 1).Create()
            devicecreated.append(deviceparam(6,0,"20"))  # default is 20 degrees
        if 7 not in Devices:
            Options = {"LevelActions":"||",
                       "LevelNames":"Off|Manual|Auto",
                       "LevelOffHidden":"true",
                       "SelectorStyle":"0"}
            Domoticz.Device(Name = "Wind direction (swing)",Unit=7,TypeName = "Selector Switch",Switchtype = 18,Image = 15,
                            Options = Options,Used = 1).Create()
            devicecreated.append(deviceparam(7,0,"10"))  # default is Manual
        if 8 not in Devices:
            Domoticz.Device(Name="Presence sensor", Unit=8, TypeName="Switch", Image=9).Create()
            devicecreated.append(deviceparam(8, 0, ""))  # default is Off
        if 9 not in Devices:
            Options = {"LevelActions":"||",
                       "LevelNames":"Disconnected|Off|Auto|Manual",
                       "LevelOffHidden":"true",
                       "SelectorStyle":"0"}
            Domoticz.Device(Name = "Control",Unit=9,TypeName = "Selector Switch",Switchtype = 18,Image = 9,
                            Options = Options,Used = 1).Create()
            devicecreated.append(deviceparam(9,0,"10"))  # default is Off
        if 10 not in Devices:
            Domoticz.Device(Name ="Thermostat Setpoint",Unit=10,Type = 242,Subtype = 1,Used = 1).Create()
            devicecreated.append(deviceparam(10,0,"21"))  # default is 21 degrees
        if 11 not in Devices:
            Domoticz.Device(Name="Presence Active", Unit=11, TypeName="Switch", Image=9,Used = 1).Create()
            devicecreated.append(deviceparam(11, 0, ""))  # default is Off
        if 12 not in Devices:
            Domoticz.Device(Name="Room temp", Unit=12, TypeName="Temperature",Used = 1).Create()
            devicecreated.append(deviceparam(12, 0, "30"))  # default is 30 degrees
        if 13 not in Devices:
            Domoticz.Device(Name="Pause requested", Unit=13, TypeName="Switch", Image=9,Used = 1).Create()
            devicecreated.append(deviceparam(13, 0, ""))  # default is Off

        # if any device has been created in onStart(), now is time to update its defaults
        for device in devicecreated:
            Devices[device.unit].Update(nValue = device.nvalue,sValue = device.svalue)

        # build lists of sensors and switches
        self.DTpresence = parseCSV(Parameters["Mode3"])
        Domoticz.Debug("DTpresence = {}".format(self.DTpresence))
        self.InTempSensors = parseCSV(Parameters["Mode4"])
        Domoticz.Debug("Inside Temperature sensors = {}".format(self.InTempSensors))

        # splits additional parameters
        params = parseCSV(Parameters["Mode5"])
        if len(params) == 7:
            self.DTDayNight = CheckParam("Day/Night Activator",params[0],0)
            self.pauseondelay = CheckParam("Pause On Delay",params[1],1)
            self.pauseoffdelay = CheckParam("Pause Off Delay",params[2],1)
            self.presenceondelay = CheckParam("Presence On Delay",params[3],2)
            self.presenceoffdelay = CheckParam("Presence Off Delay",params[4],45)
            self.reductedsp = CheckParam("Reduction temp",params[5],3)
            self.deltamax = CheckParam("delta max fan",params[6],10)
        else:
            Domoticz.Error("Error reading Mode5 parameters")


        # Check if the used control mode is ok
        if (Devices[9].sValue == "20"):
            self.ModeAuto = True
            self.ModeManual = False
            self.powerOn = 1

        elif (Devices[9].sValue == "30"):
            self.ModeAuto = False
            self.ModeManual = True
            self.powerOn = 1

        elif (Devices[9].sValue == "10"):
            self.ModeAuto = True
            self.ModeManual = False
            self.powerOn = 0


        # reset presence detection when starting the plugin.
        Devices[8].Update(nValue = 0,sValue = Devices[8].sValue)
        self.Presencemode = False
        self.Presence = False
        self.PresenceTH = False
        self.presencechangedtime = datetime.now()
        self.PresenceDetected = False

        # reset time info when starting the plugin.
        self.controlinfotime = datetime.now()
        self.PLUGINstarteddtime = datetime.now()

        self.readTemps()


    def onStop(self):
        Domoticz.Log("onStop called")
        Domoticz.Debugging(0)


    def onCommand(self,Unit,Command,Level,Color):
        Domoticz.Log("onCommand called for Unit " + str(Unit) + ": Parameter '" + str(Command) + "', Level: " + str(Level))

        # AC mode
        if (Unit == 4):
            Devices[4].Update(nValue = self.powerOn,sValue = str(Level))

        # AC fan speed
        if (Unit == 5):
            Devices[5].Update(nValue = self.powerOn,sValue = str(Level))

        # AC wind direction
        if (Unit == 7):
            Devices[7].Update(nValue = self.powerOn,sValue = str(Level))

        # AC control power
        if (Unit == 9):
            Devices[9].Update(nValue = self.powerOn,sValue = str(Level))
            if (Devices[9].sValue == "20"):
                self.ModeAuto = True
                self.ModeManual = False
                self.powerOn = 1
                Devices[3].Update(nValue = 1,sValue = "100")
                Devices[4].Update(nValue = self.powerOn,sValue = "30")  # AC mode Heat
                Devices[5].Update(nValue = self.powerOn,sValue = "10")  # AC Fan Speed Auto
                Devices[6].Update(nValue = 0,sValue = (Devices[10].sValue))  # AC setpoint = Thermostat setpoint

            elif (Devices[9].sValue == "30"):
                self.ModeAuto = False
                self.ModeManual = True
                self.powerOn = 1
                Devices[3].Update(nValue = 1,sValue = "100")
                Devices[10].Update(nValue = 0,sValue = (Devices[6].sValue))  # Thermostat setpoint = AC setpoint

            elif (Devices[9].sValue == "10"):
                self.powerOn = 0
                self.ModeAuto = True
                self.ModeManual = False
                Devices[3].Update(nValue = 0,sValue = "0")

            # Update state of all other devices
            Devices[4].Update(nValue = self.powerOn,sValue = Devices[4].sValue)
            Devices[5].Update(nValue = self.powerOn,sValue = Devices[5].sValue)
            Devices[6].Update(nValue = 0,sValue = Devices[6].sValue)
            Devices[7].Update(nValue = self.powerOn,sValue = Devices[7].sValue)
            Devices[10].Update(nValue = 0,sValue = Devices[10].sValue)

        # Thermostat setpoint
        if (Unit == 10):
            Devices[10].Update(nValue = 0,sValue = str(Level))
            Devices[6].Update(nValue = 0,sValue = (Devices[10].sValue))  # AC setpoint = Thermostat setpoint
            self.setpoint = float(Devices[10].sValue)

        # Presence active
        if (Unit == 11):
            Devices[11].Update(nValue = Devices[11].nvalue,sValue = str(Level))

        # Pause requested
        if (Unit == 13):
            Devices[13].Update(nValue = Devices[13].nvalue,sValue = str(Level))

        # check connexion
        if Devices[1].nValue == 0:
            Domoticz.Debug("ASR not connected...")
        else :
            # full check the params if ModeAuto is ON, and update the setting if necessary
            if self.ModeAuto:
                if Devices[4].sValue == "30" and Devices[6].nValue == self.setpoint:
                    Domoticz.Log("Setting OK in AutoMode")
                    Devices[6].Update(nValue = 0,sValue = str(self.setpoint))
                else:
                    Devices[4].Update(nValue = self.powerOn,sValue = "30")  # Mode is Heat in Automode
                    Devices[6].Update(nValue = 0,sValue = str(self.setpoint))

            Domoticz.Debug("ASR connected and IR Command sent...")
            requestUrl = self.buildCommandString()
            ESPcommandAPI(requestUrl)

    def onHeartbeat(self):
        Domoticz.Debug("onHeartbeat called")
        # fool proof checking.... based on users feedback
        if not all(device in Devices for device in (1, 2, 3 ,4 , 5, 6, 7, 8, 9, 10,11,12,13)):
            Domoticz.Error(
                "one or more devices required by the plugin is/are missing, please check domoticz device creation settings and restart !")
            return

        now = datetime.now()

        self.PresenceDetection()

        # checking connexion of the ESP
        if self.controlinfotime + timedelta(seconds = 30) <= now:
            self.checkconnexion()
            self.controlinfotime = datetime.now()


        # Check if the used setpoint and fan speed is ok
        if self.powerOn :
            if self.ModeAuto and Devices[1].nValue != 0 :
                if self.PresenceTH :

                    if self.intemp < (float(Devices[10].sValue) - ((self.deltamax / 10) + (self.deltamax / 20))):
                        self.setpoint = 30.0
                        Domoticz.Log("AUTOMode - used setpoint is Max 30 and fan speed Max because room temp is lower more than delta min from setpoint")
                        if not Devices[6].sValue == str(self.setpoint):
                            Devices[6].Update(nValue = 0,sValue = "30.0")  # AC setpoint = max setpoint
                            Devices[5].Update(nValue = self.powerOn,sValue = "40")  # AC Fan Speed High
                            requestUrl = self.buildCommandString()
                            ESPcommandAPI(requestUrl)
                    else :
                        self.setpoint = float(Devices[10].sValue)
                        Domoticz.Log("AUTOMode - used setpoint is normal : " + str(self.setpoint))
                        if not Devices[6].sValue == str(self.setpoint):
                            Devices[6].Update(nValue = 0,sValue = str(self.setpoint))  # AC setpoint = Thermostat setpoint
                            requestUrl = self.buildCommandString()
                            ESPcommandAPI(requestUrl)

                        if self.intemp < (float(Devices[10].sValue) - (self.deltamax / 10)):
                            if not Devices[5].sValue == "40":
                                Devices[5].Update(nValue = self.powerOn,sValue = "40")  # AC Fan Speed High
                                Domoticz.Log("Fan speed high because room temp is lower more than delta min from setpoint")
                                requestUrl = self.buildCommandString()
                                ESPcommandAPI(requestUrl)
                        else:
                            if not Devices[5].sValue == "10":
                                Devices[5].Update(nValue = self.powerOn,sValue = "10")  # AC Fan Speed Auto
                                Domoticz.Log("Fan speed auto because room temp is near from setpoint")
                                requestUrl = self.buildCommandString()
                                ESPcommandAPI(requestUrl)

                else:
                    self.setpoint = (float(Devices[10].sValue) - self.reductedsp)
                    if self.setpoint < 17:  # Setpoint Lower than range 17 to 30
                        self.setpoint = 17.0
                    Domoticz.Log("AUTOMode - used setpoint is reducted one : " + str(self.setpoint))
                    if not Devices[6].sValue == str(self.setpoint):
                        Devices[6].Update(nValue = 0,sValue = str(
                            self.setpoint))  # AC setpoint = Thermostat setpoint reducted in limit of range
                        requestUrl = self.buildCommandString()
                        ESPcommandAPI(requestUrl)

                    else:
                        if not Devices[5].sValue == "10":
                            Devices[5].Update(nValue = self.powerOn,sValue = "10")  # AC Fan Speed Auto
                            Domoticz.Log("Fan speed auto because of reducted setpoint")
                            requestUrl = self.buildCommandString()
                            ESPcommandAPI(requestUrl)

            else:
                self.setpoint = float(Devices[6].sValue)
                Domoticz.Log("MANUAL mode or ASR Not Connected")

        if self.nexttemps + timedelta(minutes = 2) <= now:
            self.readTemps()


    def WriteLog(self, message, level="Normal"):

        if self.loglevel == "Verbose" and level == "Verbose":
            Domoticz.Log(message)
        elif level == "Normal":
            Domoticz.Log(message)

    def checkconnexion(self):

        Domoticz.Debug("checkconnexion called")

        # test

        resultJson = None
        url = "http://{}/json".format(Parameters["Username"])
        Domoticz.Debug("Calling ESP Connect API: {}".format(url))
        try:
            req = request.Request(url)
            response = request.urlopen(req)
            if response.status == 200:
                Domoticz.Debug("ESP Connected -- OK")
                if (Devices[1].nValue != 1 or Devices[1].sValue == "0"):
                    Devices[1].Update(nValue = 1,sValue = "100")
                    self.ASRconnexchangedtime = datetime.now()
            else:
                Domoticz.Error("ESP Command API: http error = {}".format(response.status))

        except:
            Domoticz.Log("XXXXXXXXX ---------------------> ESP seems not connected !")
            Devices[1].Update(nValue = 0,sValue = "0")

        return resultJson


    def buildCommandString(self):
        Domoticz.Debug("onbuildCommandString called")

        # xx
        requestUrl = ""

        # Set brand
        requestUrl = requestUrl + Parameters["Password"]

        # Set power
        requestUrl = requestUrl + ","

        if (self.powerOn):
            requestUrl = requestUrl + "1"
        else:
            requestUrl = requestUrl + "0"

        # Set mode
        requestUrl = requestUrl + ","

        if (Devices[4].sValue == "0"):
            requestUrl = requestUrl + "1"
        elif (Devices[4].sValue == "10"):
            requestUrl = requestUrl + "1"
        elif (Devices[4].sValue == "20"):
            requestUrl = requestUrl + "3"
        elif (Devices[4].sValue == "30"):
            requestUrl = requestUrl + "2"
        elif (Devices[4].sValue == "40"):
            requestUrl = requestUrl + "4"
        elif (Devices[4].sValue == "50"):
            requestUrl = requestUrl + "5"

        # Set fanspeed
        requestUrl = requestUrl + ","

        if (Devices[5].sValue == "0"):
            requestUrl = requestUrl + "0"
        elif (Devices[5].sValue == "10"):
            requestUrl = requestUrl + "0"
        elif (Devices[5].sValue == "20"):
            requestUrl = requestUrl + "1"
        elif (Devices[5].sValue == "30"):
            requestUrl = requestUrl + "2"
        elif (Devices[5].sValue == "40"):
            requestUrl = requestUrl + "5"

        # Set temp
        requestUrl = requestUrl + ","

        if (Devices[6].sValue < "17"):  # Set temp Lower than range
            Domoticz.Log("Set temp is lower than authorized range ! Used one is 17")
            requestUrl = requestUrl + "17"
        elif (Devices[6].sValue > "30"):  # Set temp Upper than range
            Domoticz.Log("Set temp is upper than authorized range ! Used one is 30")
            requestUrl = requestUrl + "30"
        else:
            requestUrl = requestUrl + Devices[6].sValue

        # Set windDirection (swing, both V and H same time)
        requestUrl = requestUrl + ","

        if (Devices[7].sValue == "10"):
            requestUrl = requestUrl + "1,1"
        elif (Devices[7].sValue == "20"):
            requestUrl = requestUrl + "0,0"

        self.controlsettime = datetime.now()

        return requestUrl



    def PresenceDetection(self):

        Domoticz.Debug("PresenceDetection called")

        now = datetime.now()

        if Parameters["Mode3"] == "":
            Domoticz.Debug("presence detection mode = NO...")
            self.Presencemode = False
            self.Presence = False
            self.PresenceTH = True
            if Devices[8].nValue == 1 or Devices[11].nValue == 1:
                Devices[8].Update(nValue = 0,sValue = Devices[8].sValue)
                Devices[11].Update(nValue = 0,sValue = Devices[8].sValue)

        else:
            self.Presencemode = True
            Domoticz.Debug("presence detection mode = YES...")


            # Build list of DT switches, with their current status
            PresenceDT = {}
            devicesAPI = DomoticzAPI("type=devices&filter=light&used=true&order=Name")
            if devicesAPI:
                for device in devicesAPI["result"]:  # parse the presence/motion sensors (DT) device
                    idx = int(device["idx"])
                    if idx in self.DTpresence:  # this is one of our DT
                        if "Status" in device:
                            PresenceDT[idx] = True if device["Status"] == "On" else False
                            Domoticz.Debug("DT switch {} currently is '{}'".format(idx,device["Status"]))
                            if device["Status"] == "On":
                                self.DTtempo = datetime.now()

                        else:
                            Domoticz.Error("Device with idx={} does not seem to be a DT !".format(idx))


            # fool proof checking....
            if len(PresenceDT) == 0:
               Domoticz.Error("none of the devices in the 'dt' parameter is a dt... no action !")
               self.Presencemode = False
               self.Presence = False
               self.PresenceTH = True
               self.PresenceTHdelay = datetime.now()
               Devices[8].Update(nValue = 0,sValue = Devices[8].sValue)
               return

            if self.DTtempo + timedelta(seconds = 30) >= now:
                self.PresenceDetected = True
                Domoticz.Debug("At mini 1 DT is ON or was ON in the past 30 seconds...")
            else:
                self.PresenceDetected = False


            if self.PresenceDetected:
                if Devices[8].nValue == 1:
                    Domoticz.Debug("presence detected but already registred...")
                else:
                    Domoticz.Debug("new presence detected...")
                    Devices[8].Update(nValue = 1,sValue = Devices[8].sValue)
                    self.Presence = True
                    self.presencechangedtime = datetime.now()

            else:
                if Devices[8].nValue == 0:
                    Domoticz.Debug("No presence detected DT already OFF...")
                else:
                    Domoticz.Debug("No presence detected in the past 30 seconds...")
                    Devices[8].Update(nValue = 0,sValue = Devices[8].sValue)
                    self.Presence = False
                    self.presencechangedtime = datetime.now()


            if self.Presence:
                if not self.PresenceTH:
                    if self.presencechangedtime + timedelta(minutes = self.presenceondelay) <= now:
                        Domoticz.Debug("Presence is now ACTIVE !")
                        self.PresenceTH = True
                        self.PresenceTHdelay = datetime.now()
                        Devices[11].Update(nValue = 1,sValue = Devices[8].sValue)

                    else:
                        Domoticz.Debug("Presence is INACTIVE but in timer ON period !")
                elif self.PresenceTH:
                        Domoticz.Debug("Presence is ACTIVE !")
            else:
                if self.PresenceTH:
                    if self.presencechangedtime + timedelta(minutes = self.presenceoffdelay) <= now:
                        Domoticz.Debug("Presence is now INACTIVE because no DT since more than X minutes !")
                        self.PresenceTH = False

                    else:
                        Domoticz.Debug("Presence is ACTIVE but in timer OFF period !")
                else:
                    Domoticz.Debug("Presence is INACTIVE !")
                    if Devices[11].nValue == 1:
                        Devices[11].Update(nValue = 0,sValue = Devices[8].sValue)

    def readTemps(self):

        self.nexttemps = datetime.now()
        # fetch all the devices from the API and scan for sensors
        noerror = True
        listintemps = []
        devicesAPI = DomoticzAPI("type=devices&filter=temp&used=true&order=Name")
        if devicesAPI:
            for device in devicesAPI["result"]:  # parse the devices for temperature sensors
                idx = int(device["idx"])
                if idx in self.InTempSensors:
                    if "Temp" in device:
                        Domoticz.Debug("device: {}-{} = {}".format(device["idx"], device["Name"], device["Temp"]))
                        listintemps.append(device["Temp"])
                    else:
                        Domoticz.Error("device: {}-{} is not a Temperature sensor".format(device["idx"], device["Name"]))

        # calculate the average inside temperature
        nbtemps = len(listintemps)
        if nbtemps > 0:
            self.intemp = round(sum(listintemps) / nbtemps, 1)
            Devices[12].Update(nValue=0,
                              sValue=str(self.intemp))  # update the dummy device showing the current thermostat temp
        else:
            Domoticz.Debug("No Inside Temperature found... ")
            noerror = False


        self.WriteLog("Inside Temperature = {}".format(self.intemp), "Verbose")
        return noerror



global _plugin
_plugin = BasePlugin()

def onStart():
    global _plugin
    _plugin.onStart()

def onStop():
    global _plugin
    _plugin.onStop()

def onConnect(Connection,Status,Description):
    global _plugin
    _plugin.onConnect(Connection,Status,Description)

def onMessage(Connection,Data):
    global _plugin
    _plugin.onMessage(Connection,Data)

def onCommand(Unit, Command, Level, Color):
    global _plugin
    _plugin.onCommand(Unit, Command, Level, Color)

def onDisconnect(Connection):
    global _plugin
    _plugin.onDisconnect(Connection)

def onHeartbeat():
    global _plugin
    _plugin.onHeartbeat()

def buildCommandString():
    global _plugin
    _plugin.buildCommandString()


# Plugin utility functions ---------------------------------------------------

def parseCSV(strCSV):

    listvals = []
    for value in strCSV.split(","):
        try:
            val = int(value)
        except:
            pass
        else:
            listvals.append(val)
    return listvals


def DomoticzAPI(APICall):

    resultJson = None
    url = "http://{}:{}/json.htm?{}".format(Parameters["Address"], Parameters["Port"], parse.quote(APICall, safe="&="))
    Domoticz.Debug("Calling domoticz API: {}".format(url))
    try:
        req = request.Request(url)
        # if Parameters["Username"] != "":
        #     Domoticz.Debug("Add authentification for user {}".format(Parameters["Username"]))
        #     credentials = ('%s:%s' % (Parameters["Username"], Parameters["Password"]))
        #     encoded_credentials = base64.b64encode(credentials.encode('ascii'))
        #     req.add_header('Authorization', 'Basic %s' % encoded_credentials.decode("ascii"))

        response = request.urlopen(req)
        if response.status == 200:
            resultJson = json.loads(response.read().decode('utf-8'))
            if resultJson["status"] != "OK":
                Domoticz.Error("Domoticz API returned an error: status = {}".format(resultJson["status"]))
                resultJson = None
        else:
            Domoticz.Error("Domoticz API: http error = {}".format(response.status))
    except:
        Domoticz.Error("Error calling '{}'".format(url))
    return resultJson

def ESPcommandAPI(APICall):

    resultJson = None
    url = "http://{}/control?cmd=heatpumpir,{}".format(Parameters["Username"], parse.quote(APICall))
    Domoticz.Debug("Calling ESP Command API: {}".format(url))
    try:
        req = request.Request(url)
        response = request.urlopen(req)
        if response.status == 200:
            Domoticz.Debug("ESP Command API Sent -- OK")
        else:
            Domoticz.Error("ESP Command API: http error = {}".format(response.status))
    except:
        Domoticz.Log("XXXXXXXXX ---------------------> ESP seems not connected - Command not sent !")
    return resultJson

def ESPconnectAPI(APICall):

    resultJson = None
    url = "http://{}/{}".format(Parameters["Username"], parse.quote(APICall))
    Domoticz.Debug("Calling ESP Connect API: {}".format(url))
    try:
        req = request.Request(url)
        response = request.urlopen(req)
        if response.status == 200:
            resultJson = json.loads(response.read().decode('utf-8'))
            Domoticz.Debug("ESP Connected -- OK")
        else:
            Domoticz.Error("ESP Command API: http error = {}".format(response.status))

    except:
        Domoticz.Log("XXXXXXXXX ---------------------> ESP seems not connected !")

    return resultJson


def CheckParam(name, value, default):

    try:
        param = int(value)
    except ValueError:
        param = default
        Domoticz.Error("Parameter '{}' has an invalid value of '{}' ! defaut of '{}' is instead used.".format(name, value, default))
    return param


# Generic helper functions
def DumpConfigToLog():
    for x in Parameters:
        if Parameters[x] != "":
            Domoticz.Debug("'" + x + "':'" + str(Parameters[x]) + "'")
    Domoticz.Debug("Device count: " + str(len(Devices)))
    for x in Devices:
        Domoticz.Debug("Device:           " + str(x) + " - " + str(Devices[x]))
        Domoticz.Debug("Device ID:       '" + str(Devices[x].ID) + "'")
        Domoticz.Debug("Device Name:     '" + Devices[x].Name + "'")
        Domoticz.Debug("Device nValue:    " + str(Devices[x].nValue))
        Domoticz.Debug("Device sValue:   '" + Devices[x].sValue + "'")
        Domoticz.Debug("Device LastLevel: " + str(Devices[x].LastLevel))
    return

