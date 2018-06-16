import sys,getopt
import telnetlib
from socket import *
import time

try:
    from ncclient import manager
except Exception,err:
    print("\nncclient library cannot be imported. Please install and try again")
    sys.exit()
           
from collections import OrderedDict
import collections
class OrderedSet(collections.Set):
    def __init__(self, iterable=()):
        self.d = collections.OrderedDict.fromkeys(iterable)
    def __len__(self):
        return len(self.d)
    def __contains__(self, element):
        return element in self.d
    def __iter__(self):
        return iter(self.d)

EDIT_CONFIG_HEADER = """<rpc message-id="101" xmlns="urn:ietf:params:xml:ns:netconf:base:1.0" >
<edit-config>
 <target>
  <candidate />
 </target>
 <config xmlns:xc="urn:ietf:params:xml:ns:netconf:base:1.0" >"""

EDIT_CONFIG_FOOTER = """
 </config>
</edit-config>
</rpc>
##"""

def initialize():
    global hostname, ssh_port, telnet_port, netconf_summary, sun_user, sun_password,interactive_cli, cli_commands_interactive, models_type 
    global cli_config_file, log_file, edit_config_file, uncovered_cli_file
    hostname=telnet_port=ssh_port=sun_user=sun_password=models_type=""
    interactive_cli=1
    input_error_string=""" --host [<agent address>] --netconfport [<ssh port>] --telnetport [<telnet port>] --clifile [<cli config file>] --username [<user name>] --password [<password>] 
--models [<native | openconfig>] """
    
    try:
        opts,args = getopt.getopt(sys.argv[1:],"",["host=","netconfport=","telnetport=","clifile=","username=","password=","models="])
    except getopt.GetoptError:
        print ("\nUsage: "+sys.argv[0]+input_error_string+"\n")
        sys.exit()
    
    for opt,arg in opts:
        if opt in ("--host"):
            hostname=arg
        elif opt in ("--netconfport"):
            ssh_port=arg
        elif opt in ("--telnetport"):
            telnet_port=arg
        elif opt in ("--clifile"):
            try:
                cli_config_file = open(arg)
                interactive_cli=0
                contents=cli_config_file.read()
                cli_config_file.seek(0,0)
                if len(contents.strip())==0 or contents.strip().lower()=="commit":
                    print ("\nCLI file empty")
                    sys.exit()
            except Exception,err:
                print ("\nCLI file not found.")
                sys.exit()
        elif opt in ("--username"):
            sun_user = arg
        elif opt in ("--password"):
            sun_password = arg
        elif opt in ("--models"):
            models_type = arg
        else:
            print ("\nUsage: "+sys.argv[0]+input_error_string+"\n") 
            sys.exit()
    log_file=open("logs.txt","w")
    edit_config_file=open("model_log.xml","w")
    uncovered_cli_file=open("uncovered_cli.txt","w")
    if(len(hostname)==0 or len(ssh_port)==0 or len(telnet_port)==0 or len(sun_user)==0 or len(sun_password)==0):
        print ("\nUsage: "+sys.argv[0]+input_error_string+"\n")
        sys.exit()
    netconf_summary={   
                     1:"1. NETCONF - Send GET_CONFIG for Base Configuration       : ",
                     2:"2. CLI - Send CLI Configuration and show running-config   : ",
                     3:"3. NETCONF - Send GET_CONFIG for Complete Configuration   : ",
                     4:"4. CLI - Rollback to Base Configuration                   : ",  
                     5:"5. NETCONF - Send EDIT_CONFIG and show running-config     : ",
                     6:"6. CLI- Rollback to Base Configuration                    : ",
                     7:"7. CLI NETCONF Configurations Match                       : ",}
       
    if(len(models_type)==0 or (models_type.find('native')==-1 and models_type.find('openconfig')==-1)):
        models_type="native"
    
    if(interactive_cli):
        cli_commands_interactive=""
        print("\nEnter the CLI configurations along with commit:\n")
        while 1:
            inp_cli=sys.stdin.readline()
            cli_commands_interactive=cli_commands_interactive+inp_cli
            if(cli_commands_interactive.find("commit")!=-1):
                break;
        if(cli_commands_interactive.strip().lower()=="commit"):
            log_file.write("\n"+fn_name+"Empty Cli Configurations")
            summary(1,"FAIL")

def netconf_config():
    log_file.write("-----------------------Inside function: netconf_config()-------------------------")
    fn_name="netconf_config() : "
    global mc, diff_yang_models, net_conf_response
    
    try:
        mc=manager.connect(host=hostname,port=ssh_port,username=sun_user,password=sun_password,allow_agent=False,look_for_keys=False,hostkey_verify=True)
    except Exception, err:
        log_file.write("\n"+fn_name+"Failed to connect Netconf agent at: "+str(hostname)+":"+str(ssh_port)+"  "+str(err))
        summary(1,"FAIL")

    log_file.write("\n--------------------------------------Connected to NETCONF ----------------------------------")
    get_conf_base_msg_list=ncclient_get_config(mc,fn_name,"Failed to receive the GET_CONFIG for base config: ",1)
    log_file.write("\n---------------------------------- Received GET_CONFIG-Base ------------------------------------"+"\n"+mc.get_config('running').data_xml)
    summary(1,"PASS")

    cli_config(2)            
    
    get_conf_msg_list=ncclient_get_config(mc,fn_name,"Failed to receive the GET_CONFIG: ",3)
    log_file.write("\n---------------------------------Received GET_CONFIG -----------------------------------------"+"\n"+mc.get_config('running').data_xml)
    summary(3,"PASS")
    
    revert_base_config(4)

    base_dict=OrderedDict()
    base_cli_dict=OrderedDict()
    base_dict=xml_to_dict(get_conf_base_msg_list,1,len(get_conf_base_msg_list)-1)
    base_cli_dict=xml_to_dict(get_conf_msg_list,1,len(get_conf_msg_list)-1)
    b_keys=base_dict.keys()
    bc_keys=base_cli_dict.keys()
    diff_yang_models=[]
    edit_config=EDIT_CONFIG_HEADER
    request="""<config xmlns:xc="urn:ietf:params:xml:ns:netconf:base:1.0" >"""
    if(models_type.find("native")!=-1):
       model_only="cisco.com"
    elif(models_type.find("openconfig")!=-1):
        model_only="openconfig.net"
        
    for key in bc_keys:
        if(key not in b_keys):
            if(key.find(model_only) != -1):
                diff_yang_models.append(key)
                edit_config=edit_config+"\n"+base_cli_dict.get(key)
                request=request+"\n"+base_cli_dict.get(key)
        elif(base_cli_dict.get(key) != base_dict.get(key)):
            if(key.find(model_only) != -1):
                diff_yang_models.append(key)
                edit_config=edit_config+"\n"+base_cli_dict.get(key)
                request=request+"\n"+base_cli_dict.get(key) 
    edit_config=edit_config+EDIT_CONFIG_FOOTER
    edit_config_file.write(edit_config)
    request=request+"\n"+"</config>"
    
    try:
        mc.edit_config(request,format='xml',target='candidate', default_operation=None, test_option=None, error_option=None)
        log_file.write("\n---------------------------------- Sent EDIT_CONFIG  ------------------------------------"+"\n"+request)
        mc.commit(confirmed=False, timeout=None, persist=None)  
    except Exception, err:
        log_file.write(fn_name+"\nFailed to send the EDIT_CONFIG/COMMIT: "+str(err))
        if(model_only.find('openconfig.net')!=-1):
            if(len(request.splitlines())==2):
                log_file.write(fn_name+"\n\nThere is no openconfig request to capture the required configuration.")
                summary(5,"FAIL")
                print("There is no openconfig request to capture the required configuration.")
                sys.exit()
            else:
                log_file.write(fn_name+"\n\nThe openconfig request is not accepted by the system.")
                summary(5,"FAIL")
                print("The openconfig request is not accepted by the system.") 
                sys.exit()
        summary(5,"FAIL")
        sys.exit()
        
    log_file.write("\n----------------------------------Sent show running-config------------------------------------")
    net_conf_response=show_running_config(fn_name,"Show running config failed: ",5)   
    summary(5,"PASS")
    
    revert_base_config(6)
    tn.close()
    mc.close_session()
    
def cli_config(error_number):
    fn_name="cli_config : "   
    global tn, cli_response
    
    try:
        tn=telnetlib.Telnet(gethostbyname(hostname),int(telnet_port))
    except Exception, err:
        log_file.write("\n"+fn_name+"Failed to open telnet connection: "+str(hostname)+"  "+str(telnet_port)+"  "+str(err))
        summary(error_number,"FAIL")

    log_file.write("\n------------------------- Connected via Telnet to router to send CLI commands ----------------")
    try:
        tn.read_until("Username: ")
        tn.write(sun_user+"\n")
        tn.read_until("Password: ")
        tn.write(sun_password+"\n")
        if(tn.read_until("Username: ",1).find("Username:")!=-1):
            log_file.write("\n"+fn_name+"Username/Password are wrong")
            summary(error_number,"FAIL")
        tn.write("term length 0\n") 
        cli_commands=cli_commands_interactive.splitlines() if(interactive_cli) else cli_config_file
        log_file.write("\n"+"config")
        tn.write("config"+"\n")
        count = 1
        for line in cli_commands:
            if(len(line.strip())==0):
                continue
            log_file.write("\n"+line+"  ")
            log_file.write(" Time: "+time.ctime())                           
            tn.write(line+"\n")
            if(line.strip().lower().find('commit')!=-1):
                time.sleep(2)
                tn.write("end\n")
            if(tn.read_until("Invalid input detected at",1).find("%")!=-1):
                log_file.write("\n"+fn_name+"Incorrect configurations in Test CLI")
                summary(error_number,"FAIL")            
    except Exception, err:
        log_file.write("\n"+fn_name+"Initialization/Base Config/CLI Config Failed"+str(err))
        tn.close()
        summary(error_number,"FAIL")
    
    log_file.write("\n----------------------------------Sent show running-config------------------------------------")
    cli_response=show_running_config(fn_name,"Show running config failed: ",error_number)
    summary(error_number,"PASS")

def show_running_config(fn_name,fail_string,error_number):
    message=""
    try:
        tn.write("show running-config\n")
        tn.read_until("Building configuration...")
        message=tn.read_until("\nend")
    except Exception, err:
        log_file.write("\n"+fn_name+fail_string+str(err))
        tn.close()
        summary(error_number,"FAIL")
    return message

def revert_base_config(error_number):
    fn_name="revert_base_config : "   
    try:        
        tn.write("rollback configuration last 1\n")
        log_file.write("\n------------------Configuration Rollback Message--------------------------\n")
        tn.read_until("Loading Rollback Changes.")
        log_file.write(tn.read_until("1 commits."))
    except Exception, err:
        log_file.write("\n"+fn_name+"Revert to Base Config Failed. "+str(err))
        tn.close()
        summary(error_number,"FAIL")
    summary(error_number,"PASS")
        
def ncclient_get_config(connection,fn_name,fail_string,error_number):
    try:
        message=connection.get_config('running').data_xml.splitlines()  
    except Exception, err:
        log_file.write("\n"+fn_name+fail_string+str(err))
        summary(error_number,"FAIL")
    return message
    
def xml_to_dict(message_list, start, end):
    dict=OrderedDict()
    tag_space=message_list[start].split('<')[0]
    for i in range(start,end):
        if(message_list[i].split('<')[0]==tag_space and message_list[i].find('xmlns=')!=-1):
            dict[message_list[i]]=message_list[i]
        elif(message_list[i].find('#')!=-1 or len(message_list[i].strip())==0):
            continue
        else:
            keys=dict.keys()
            length=len(keys)
            last_inserted_key=keys[length-1]
            dict[last_inserted_key]=dict.get(last_inserted_key)+"\n"+message_list[i]
    return dict
    
def summary(index, value):
    if(index==1):
        print ("\n================================Summary=========================================\n")
    print (netconf_summary[index]+value)
       
    if(value=="FAIL"):
        print ("\nRefer logs.txt for detailed information.\n")
        if(index!=5):
            sys.exit()

def validation():   
    log_file.write("\n\n---------------------Inside function: validation()-------------------------------------------")
    log_file.write("\n----------------------------------------- CLI Reponse ---------------------------------------"+"\n"+cli_response)
    log_file.write("\n--------------------------------------- NetConf Reponse -------------------------------------"+"\n"+net_conf_response)
    cli_response_list=cli_response.splitlines()
    net_conf_response_list=net_conf_response.splitlines()
    del cli_response_list[2]
    del net_conf_response_list[2]
    result_set=OrderedSet(cli_response_list)^OrderedSet(net_conf_response_list)
    status="PASS" if(len(result_set)==0) else "FAIL"
    print ("7. CLI NETCONF Configurations match                       : "+status+"\n")
    log_file.write("\n"+status+": Status of configurations match.\n")
    log_file.write("\n---------------------------------------------Yang Models for CLI------------------------------\n")
    print ("----------------------------Yang Models for CLI---------------------------------")
    for diff_yang in diff_yang_models:
        model=diff_yang.split('"')[1]
        if(model!="http://cisco.com/ns/yang/Cisco-IOS-XR-aaa-lib-cfg" and model!="http://tail-f.com/ns/aaa/1.1"):
            print (model)
            log_file.write(model+"\n")          
    if(status=="FAIL"):
        print ("\n-------------------------Uncovered Configurations-------------------------------")
        log_file.write("\n----------------------------------------Uncovered Configurations----------------------------------\n")
        uncovered_cli_file.write("Uncovered Configurations:"+"\n")
        for result in result_set:
            print (result)
            log_file.write(result+"\n")
            uncovered_cli_file.write(result+"\n")
    print ("\n--------------------------------------------------------------------------------")
    print ("Refer model_log.xml-request XML, uncovered_cli.txt-uncovered CLI and logs.txt-logs.\n")  

if __name__ == "__main__":
    initialize()
    netconf_config()
    validation()
