#===============================================================================
# Created:        22 May 2019
# @author:        AP (adapated from Jesse Wilson)
# Description:    This library implements the Anaplan API to get lists of model resources, upload files to Anaplan server, 
#                 download files from Anaplan server, and execute actions.
#===============================================================================

import requests
import json
import os
from anaplanapi2 import anaplan_auth
from anaplanapi2 import anaplan_resource_dictionary
from time import sleep
import logging
import io
import pandas

#===============================================================================
# Defining global variables
#===============================================================================
__base_url__ = "https://api.anaplan.com/2/0/workspaces"
__post_body__ = {
            "localeName":"en_US"
        }
__BYTES__ = 1024 * 1024
__chunk__ = 0
#===========================================================================
# This function reads the authentication type, Basic or Certificate, then passes
# the remaining variables to anaplan_auth to generate the authorization for Anaplan API
#===========================================================================
def generate_authorization(auth_type, *args):    
    '''
    :param auth_type: 
    :param *args: Path to public certificate, and private key if auth_type='certificate'; Anaplan Username, Anaplan 
                  Password, and private key if auth_type='basic'
    '''
        
    if auth_type.lower() == 'basic':
        header_string = anaplan_auth.basic_auth_header(args[0], args[1])
        
        authorization = anaplan_auth.authenticate(anaplan_auth.auth_request(header_string, body=None))
        return authorization
    elif auth_type.lower() == 'certificate':
        privKey = args[0]
        pubCert = args[1]
        
        header_string = anaplan_auth.certificate_auth_header(pubCert)
        post_data = anaplan_auth.generate_post_data(privKey)
        authorization = anaplan_auth.authenticate(anaplan_auth.auth_request(header_string, post_data))
        if not authorization[:5] == "Error":
            return authorization    
    else:
        return "Please enter a valid authentication method: Basic or Certificate"

#===========================================================================
# This function reads a flat file of an arbitrary size and uploads to Anaplan
# in chunks of a size defined by the user.
#===========================================================================
def flat_file_upload(conn, fileId, chunkSize, file):
    '''
    :param conn: AnaplanConnection object which contains authorization string, workspace ID, and model ID
    :param fileId: ID of the file in the Anaplan model
    :param chunkSize: Desired size of the chunk, in megabytes
    :param file: Path to the local file to be uploaded to Anaplan
    '''
    
    #Setting local variables for connection details
    authorization = conn.authorization
    workspaceGuid = conn.workspaceGuid
    modelGuid = conn.modelGuid
    
    #Restrict users from entering a value for chunkSize greater than 50mb to prevent issues with API server
    if chunkSize > 50:
        return "Chunk size must be 50mb or less."
    else:
        
        #Assigning the size of the local file in MB
        file_size = os.stat(file).st_size / __BYTES__
        file_data = ""
        
        post_header = {
                "Authorization": authorization,
                  "Content-Type":"application/json"
            }
        put_header = {
                "Authorization": authorization,
                "Content-Type":"application/octet-stream"
            }
        file_metadata_start = {
                    "id":fileId,
                    "chunkCount":-1
                      }
        file_metadata_complete = {
                      "id":fileId,
                      "chunkCount": file_size / (__BYTES__ * chunkSize)
                     }
        url = __base_url__ + "/" +workspaceGuid + "/models/" + modelGuid + "/files/" + fileId
    
        start_upload_post = requests.post(url, headers=post_header, json=file_metadata_start)
        #Confirm that the metadata update for the requested file was OK before proceeding with file upload
        if start_upload_post.ok:
            complete = True #Variable to track whether file has finished uploaded
            with open(file, "rt") as f: #Loop through the file, reading a user-defined number of bytes until complete
                chunkNum = 0
                while True:
                    buf=f.readlines(__BYTES__ * chunkSize)
                    if not buf:
                        break
                    for item in buf:
                        file_data += item
                    file_upload = requests.put(url + "/chunks/" + str(chunkNum), headers=put_header, data=file_data)
                    logging.debug("Uploading chunk " + str(chunkNum + 1) +", Status: " + file_upload.status_code)
                    if not file_upload.ok:
                        complete = False #If the upload fails, break the loop and prevent subsequent requests. Print error to screen
                        logging.debug("Error " + str(file_upload.status_code) + '\n' + file_upload.text)
                        break
                    else:
                        chunkNum += 1    
            if complete:
                complete_upload = requests.post(url + "/complete", headers=post_header, json=file_metadata_complete)
                if complete_upload.ok:
                    return "File upload complete, " + str(chunkNum) + " chunk(s) uploaded to the server."
                else:
                    return "There was an error with your request: " + complete_upload.status_code + " " + complete_upload.text
        else:
            return "There was an error with your request: " + start_upload_post.status_code + " " + start_upload_post.text

#===========================================================================
# This function uploads a data stream to Anaplan in a chunk of no larger
# than 50mb. 
#===========================================================================
def stream_upload(conn, file_id, buffer, **args):
    '''
    :param conn: AnaplanConnection object which contains authorization string, workspace ID, and model ID
    :param fileId: ID of the file in the Anaplan model
    :param buffer: dataframe to upload to Anaplan file
    :param *args: Once complete, this should be True to complete upload and reset chunk counter
    '''
    
    global __chunk__
    chunk_temp=0
    #Setting local variables for connection details
    authorization = conn.authorization
    workspaceGuid = conn.workspaceGuid
    modelGuid = conn.modelGuid
    
    post_header = {
                    "Authorization": authorization,
                      "Content-Type":"application/json"
                }
    put_header = {
                    "Authorization": authorization,
                    "Content-Type":"application/octet-stream"
                }
    stream_metadata_start = {
                        "id":file_id,
                        "chunkCount":-1
                          }
    url = __base_url__ + "/" +workspaceGuid + "/models/" + modelGuid + "/files/" + file_id
    
    if(len(args) > 0):  
        file_metadata_complete = {
                      "id":file_id,
                      "chunkCount": __chunk__
                     }
        complete_upload = requests.post(url=url + "/complete", headers=post_header, json=file_metadata_complete)
        chunk_temp=__chunk__
        __chunk__ = 0
        if complete_upload.ok:
            return "Upload complete, " + str(chunk_temp) + " chunk(s) uploaded to the server."
        else:
            return "There was an error completing your upload: " + complete_upload.status_code + '\n' + complete_upload.text     
        
    else:    
        logging.debug("Starting file upload...")
        if(len(buffer.encode()) > (__BYTES__ * 50)):
            return "Buffer too large, please send less than 50mb of data."
        else:    
            if __chunk__==0:
                start_upload_post = requests.post(url, headers=post_header, json=stream_metadata_start)
                #Confirm that the metadata update for the requested file was OK before proceeding with file upload
                if not start_upload_post.ok:
                    return "There was an error with your request: " + start_upload_post.status_code + " " + start_upload_post.text
                
            stream_upload = requests.put(url + "/chunks/" + str(__chunk__), headers=put_header, data=buffer)
            if not stream_upload.ok:
                return "Error " + str(stream_upload.status_code) + '\n' + stream_upload.text
            else:
                __chunk__ += 1
                return "Uploading chunk " + str(__chunk__) + ", Status: " + str(stream_upload.status_code)
            
#===========================================================================
# This function uploads a dataframe to Anaplan in chunks of no larger
# than 50mb. 
#===========================================================================
def stream_upload_df(conn, file_id, df, chunk_size):
    '''
    :param conn: AnaplanConnection object which contains authorization string, workspace ID, and model ID
    :param fileId: ID of the file in the Anaplan model
    :param df: datafame to upload to Anaplan file
    :param chunk_size: chunk row size
    '''
    str
    start_index=0
    end_index=0
    num_rows=len(df.index)
    while end_index<num_rows:
        start_index=end_index
        end_index=start_index + chunk_size
        chunk_df=df[start_index:end_index]
        str_buffer=io.StringIO()
        chunk_df.to_csv(str_buffer,index=False,header=(start_index==0),chunksize=chunk_size)
        stream_upload(conn, file_id, str_buffer.getvalue())
        str_buffer.close()
        
    #complete the upload
    stream_upload(conn, file_id, "",complete=True)
    return
#===========================================================================
# This function reads the ID of the desired action to run, POSTs the task
# to the Anaplan API to execute the action, then monitors the status until
# complete.
#===========================================================================
def execute_action(conn, actionId, retryCount):
    '''
    :param conn: AnaplanConnection object which contains authorization string, workspace ID, and model ID
    :param actionId: ID of the action in the Anaplan model
    :param retryCount: The number of times to attempt to retry the action if it fails
    '''
    
    authorization = conn.authorization
    workspaceGuid = conn.workspaceGuid
    modelGuid = conn.modelGuid
    
    post_header = {
            'Authorization': authorization,
            'Content-Type':'application/json'
        }
    
    if actionId[:3] == "112":
        logging.debug("Running action " + actionId)
        url = __base_url__ + "/" +workspaceGuid + "/models/" + modelGuid + "/imports/" + actionId + "/tasks"
        taskId = run_action(url, post_header, retryCount)
        return check_status(url, taskId, post_header)
    elif actionId[:3] == "116":
        logging.debug("Running action " + actionId)
        url = __base_url__ + "/" +workspaceGuid + "/models/" + modelGuid + "/exports/" + actionId + "/tasks"      
        taskId = run_action(url, post_header, retryCount)
        return check_status(url, taskId, post_header)
    elif actionId[:3] == "117":
        logging.debug("Running action " + actionId)
        url = __base_url__ + "/" +workspaceGuid + "/models/" + modelGuid + "/actions/" + actionId + "/tasks"
        taskId = run_action(url, post_header, retryCount)
        return check_status(url, taskId, post_header)
    elif actionId[:3] == "118":
        logging.debug("Running action " + actionId)
        url = __base_url__ + "/" +workspaceGuid + "/models/" + modelGuid + "/processes/" + actionId + "/tasks"
        taskId = run_action(url, post_header, retryCount)
        return check_status(url, taskId, post_header)
    else:
        logging.debug("Incorrect action ID provided!")

#===========================================================================
# This function executes the Anaplan action, if there is a server error it
# will wait, and retry a number of times defined by the user. Once the task
# is successfully created, the task ID is returned.
#===========================================================================
def run_action(url, post_header, retryCount):
    '''
    @param url: POST URL for Anaplan action
    @param post_header: Authorization header string
    @param retryCount: Number of times to retry executino of the action
    '''
    
    state = 0
    sleepTime = 10
        
    while True:
        run_action = requests.post(url, headers=post_header, json=__post_body__)
        
        if run_action.status_code != 200 and state < retryCount:
            sleep(sleepTime)
            run_action = requests.post(url, headers=post_header, json=__post_body__)
            state += 1
            sleepTime = sleepTime * 1.5
        else:
            break
    taskId = json.loads(run_action.text)
    taskId = taskId["task"]
    
    return taskId["taskId"]
        
#===========================================================================
# This function reads the ID of the desired import or process to run with
# mapping parameters declared, POSTs the task to the Anaplan API to execute 
# the action, then monitors the status until complete.
#===========================================================================
def execute_action_with_parameters(conn, actionId, retryCount, **params):
    '''
    :param conn: AnaplanConnection object which contains authorization string, workspace ID, and model ID
    :param actionId: ID of the action in the Anaplan model
    :param retryCount: The number of times to attempt to retry the action if it fails
    '''
    
    authorization = conn.authorization
    workspaceGuid = conn.workspaceGuid
    modelGuid = conn.modelGuid
    
    post_header = {
            'Authorization': authorization,
            'Content-Type':'application/json'
        }
    
    body = ""
    
    if len(params) > 1:
        for key, value in params.items():
            body += "\"entityType:\"" + key + "\"" + ",\"entityType:\"" + value + "\"" + ","
        body = body[:-1]
        body = "[" + body + "]"
    else:
        for key, value in params.items():
            body += "[\"" + key + "\"" + ":" + "\"" + value + "\"]"
    
    
    post_body = {
                    "localeName":"en_US","mappingParameters": body
                }
    
    if actionId[:3] == "112":
        logging.debug("Running action " + actionId)
        url = __base_url__ + "/" +workspaceGuid + "/models/" + modelGuid + "/imports/" + actionId + "/tasks"
        taskId = run_action_with_parameters(url, post_header, retryCount, post_body)
        return check_status(url, taskId, post_header)
    elif actionId[:3] == "118":
        logging.debug("Running action " + actionId)
        url = __base_url__ + "/" +workspaceGuid + "/models/" + modelGuid + "/processes/" + actionId + "/tasks"
        taskId = run_action(url, post_header, retryCount, post_body)
        return check_status(url, taskId, post_header)
    else:
        logging.debug("Incorrect action ID provided! Only imports and processes may be executed with parameters.")

#===========================================================================
# This function executes the Anaplan import or process with mapping parameters,
# if there is a server error it will wait, and retry a number of times
# defined by the user. Once the task is successfully created, the task ID is returned.
#===========================================================================
def run_action_with_parameters(url, post_header, retryCount, post_body):
    '''
    @param url: POST URL for Anaplan action
    @param post_header: Authorization header string
    @param retryCount: Number of times to retry executino of the action
    '''
    
    state = 0
    sleepTime = 10
        
    while True:
        run_action = requests.post(url, headers=post_header, json=post_body)
        if run_action.status_code != 200 and state < retryCount:
            sleep(sleepTime)
            run_import = requests.post(url, headers=post_header, json=post_body)
            state += 1
            sleepTime = sleepTime * 1.5
        else:
            break
    taskId = json.loads(run_import.text)
    
    return taskId["taskId"]

#===========================================================================
# This function monitors the status of Anaplan action. Once complete it returns
# the JSON text of the response.
#===========================================================================        
def check_status(url, taskId, post_header):
    '''
    @param url: Anaplan task URL
    @param taskId: ID of the Anaplan task executed
    @param post_header: Authorization header value
    '''
    
    while True:
        get_status = requests.get(url + "/" + taskId, headers=post_header)
        status = json.loads(get_status.text)
        status = status["task"]["taskState"]
        if status == "COMPLETE":
            results = json.loads(get_status.text)
            results = results["task"]
            break   
    
    return parse_task_response(results, url, taskId, post_header)
    
#===========================================================================
# This function reads the JSON results of the completed Anaplan task and returns
# the job details.
#===========================================================================
def parse_task_response(results, url, taskId, post_header):
    '''
    :param results: JSON dump of the results of an Anaplan action
    '''
    job_status = results["currentStep"]
    failure_alert = str(results["result"]["failureDumpAvailable"]) 
    
    if job_status == "Failed.":
        error_message = str(results["result"]["details"][0]["type"])
        logging.debug("The task has failed to run due to an error: " + error_message) #changed localMessageText to type 
        return "The task has failed to run due to an error: " + error_message
    else:
        if failure_alert == "True":
            dump = requests.get(url + "/" + taskId + '/' + "dump", headers=post_header)
            dump = dump.text
        success_report = str(results["result"]["successful"])
        if 'details' not in results["result"]:
            anaplan_process_dump = ""
            error_detail = ""
            load_detail = ""
            failure_details = ""
            for nestedResults in results["result"]["nestedResults"]:
                process_subfailure = str(nestedResults["failureDumpAvailable"])
                object_id = str(nestedResults["objectId"])
                load_detail = load_detail + "Process action " + object_id + " completed. Failure: " + process_subfailure + '\n'
                if process_subfailure == "True":
                        local_message = str(nestedResults["details"][0]["type"]) #changed localMessageText to type 
                        details = nestedResults["details"][0]["values"]
                        for i in details:
                            error_detail = error_detail + str(i or '') + '\n' #changed i to str(i or '')
                        dump = requests.get(url + "/" + taskId + '/' + "dumps" + '/' + object_id,  headers=post_header)
                        report = "Error dump for " + object_id + '\n' + dump.text
                        anaplan_process_dump += report  
                        failure_details = failure_details + local_message      
            if anaplan_process_dump != "":
                logging.debug("The requested job is " + job_status)
                return load_detail + '\n' + "Details:" + '\n' + error_detail + '\n' + "Failure dump(s):" + '\n' + anaplan_process_dump
            else:
                logging.debug("The requested job is " + job_status)
                return load_detail
        else:
            load = str(results["result"]["details"][0]["type"]) #changed localMessageText to type 
            load_detail = ""
            for i in results["result"]["details"][0]["values"]:
                load_detail = load_detail + str(i or '') + '\n' #changed i to str(i or '')
            if failure_alert == "True":
                logging.debug("The requested job is " + job_status)
                return "Failure Dump Available: " + failure_alert + ", Successful: " + success_report + '\n' + "Load details:" + '\n' + load + '\n' + load_detail + '\n' + "Failure dump:" + '\n' + dump
            else:
                logging.debug("The requested job is " + job_status)
                return "Failure Dump Available: " + failure_alert + ", Successful: " + success_report + '\n' + "Load details:" + '\n' + load + '\n' + load_detail

#===========================================================================
# This function queries the Anaplan model for a list of the desired resources:
# files, actions, imports, exports, processes and returns the JSON response.
#===========================================================================
def get_list(conn, resource):
    '''
    :param conn: AnaplanConnection object which contains authorization string, workspace ID, and model ID
    :param resource: The Anaplan model resource to be queried and returned to the user
    '''
    
    authorization = conn.authorization
    workspaceGuid = conn.workspaceGuid
    modelGuid = conn.modelGuid
    
    get_header = {
            'Authorization': authorization,
            'Content-Type':'application/json'
    }
    url = __base_url__ + "/" + workspaceGuid + "/models/" + modelGuid + "/" + resource.lower()
    
    logging.debug("Fetching " + resource + "...")
    
    response = requests.get(url, headers=get_header)
    response = response.text
    response = json.loads(response)
    
    logging.debug("Finished fetching " + resource + ".")
     
    return response[resource]

#===========================================================================
# This function reads the JSON response of the Anaplan resources, prints to screen.
#===========================================================================
def parse_get_response(response):
    '''
    :param response: JSON text of Anaplan model resources
    '''
    
    for item in response:
        if item == None:
            break
        else:
            logging.debug("Name: " + item["name"] + '\n' + "ID: " + item["id"] + '\n')
            
#===========================================================================
# This function downloads a file from Anaplan to the specified path.
#===========================================================================
def get_file(conn, fileId, location):
    ''' 
    :param conn: AnaplanConnection object which contains authorization string, workspace ID, and model ID
    :param fileId: ID of the Anaplan file to download
    :param location: Location on the local machine where the download will be saved
    '''
    
    chunk = 0
    details = get_file_details(conn, fileId)
    chunk_count = details[0]
    file_name = details[1]
    
    authorization = conn.authorization
    workspaceGuid = conn.workspaceGuid
    modelGuid = conn.modelGuid
    
    get_header = {
                "Authorization": authorization,
    }    
    
    
    local_file = open(location + file_name, "w+",newline='')
    
    logging.debug("Fetching file " + fileId + "...")
    
    while int(chunk)<int(chunk_count):
        url = __base_url__ + "/" + workspaceGuid + "/models/" + modelGuid + "/files/" + fileId + "/chunks/" + str(chunk)
        file_contents = requests.get(url, headers=get_header)
        
        if file_contents.ok:
            local_file.write(file_contents.text)
        else:
            return "There was a problem fetching the file: " + file_contents.text
            break
        chunk = str(int(chunk) + 1)
    local_file.close
    
    return "File successfully downloaded to " + location + file_name        

#===========================================================================
# This function downloads a file from Anaplan to a Pandas Dataframe.
#===========================================================================
def get_file_as_dataframe(conn, fileId, delimiter=",",header_row=0,index_col=None,skiprows=None):
    ''' 
    :param conn: AnaplanConnection object which contains authorization string, workspace ID, and model ID
    :param fileId: ID of the Anaplan file to download
    :param delimiter: Delimiter to use default ,
    :param header: Row number(s) to use as the column names, and the start of the data
    :param index_col: Column(s) to use as the row labels of the DataFrame, either given as string name or column index
    :param skiprows: Line numbers to skip (0-indexed) or number of lines to skip (int) at the start of the file
    '''
    df=pandas.DataFrame()
    chunk = 0
    details = get_file_details(conn, fileId)
    chunk_count = details[0]
    file_name = details[1]
    
    authorization = conn.authorization
    workspaceGuid = conn.workspaceGuid
    modelGuid = conn.modelGuid
    
    get_header = {
                "Authorization": authorization,
    }    
    
    
    logging.debug("Fetching file " + fileId + "...")
    
    while int(chunk)<int(chunk_count):
        url = __base_url__ + "/" + workspaceGuid + "/models/" + modelGuid + "/files/" + fileId + "/chunks/" + str(chunk)
        file_contents = requests.get(url, headers=get_header)
        if file_contents.ok:
            #urlData = file_contents.content
            #rawData = pandas.read_csv(io.StringIO(urlData.decode('utf-8')))
            if chunk==0:
                df = pandas.read_csv(io.StringIO(file_contents.text),header=header_row, sep=delimiter)
            else:
                rawData = pandas.read_csv(io.StringIO(file_contents.text),header=None,names=df.columns, sep=delimiter)
                df=pandas.concat([df,rawData],ignore_index=True)
        else:
            return "There was a problem fetching the file: " + file_contents.text
            break
        chunk = str(int(chunk) + 1)
    
    return df      
    

#===============================================================================
# This function queries the model for name and chunk count of a specified file
#===============================================================================
def get_file_details(conn, fileId):
    '''
    :param conn: AnaplanConnection object which contains authorization string, workspace ID, and model ID
    :param fileId: ID of the Anaplan file to download
    '''
    
    chunkCount = 0
    file_name = ""
    
    authorization = conn.authorization
    workspaceGuid = conn.workspaceGuid
    modelGuid = conn.modelGuid
    
    get_header = {
                "Authorization": authorization,
    }    
    
    url = __base_url__ + "/" + workspaceGuid + "/models/" + modelGuid + "/files/"
    files_list = requests.get(url, headers=get_header)
    
    if files_list.ok:
        files=json.loads(files_list.text)
        files=files["files"]
        for item in files:
            temp_id=str(item["id"])
            chunkCount=item["chunkCount"]
            file_name=str(item["name"])
            if temp_id == fileId:
                break
    
    return [chunkCount, file_name]

#===============================================================================
# This function returns the user's Anaplan ID
#===============================================================================
def get_user_id(conn):
    '''
    @param conn: AnaplanConnection object which contains authorization string, workspace ID, and model ID
    '''
    
    url='https://api.anaplan.com/2/0/users/me'
    
    authorization = conn.authorization

    get_header = {
                "Authorization": authorization
                }
    
    logging.debug("Fetching user ID...")
    
    user_details=requests.get(url, headers=get_header)
    user_details=json.loads(user_details.text)
    
    user_id=user_details["user"]["id"]
    
    logging.debug("Finished fetching user ID.")
    
    return user_id

#===============================================================================
# This function queries Anaplan for a list of models the designated user has
# access to and returns this as a JSON array.
#===============================================================================
def get_models(conn, user_id):
    '''
    @param conn: AnaplanConnection object which contains authorization string, workspace ID, and model ID
    @param user_id: 32-character string that uniquely identifies the Anaplan user
    '''
    
    url="https://api.anaplan.com/2/0/users/" + str(user_id) + "/models"
    
    authorization = conn.authorization

    get_header = {
                "Authorization": authorization , 
                "Content-Type":"application/json"
                }
    
    logging.debug("Fetching models...")
    
    model_list=requests.get(url, headers=get_header)
    model_list=json.loads(model_list.text)
    
    model_list=model_list["models"]
    
    logging.debug("Finished fetching models.")
    
    return model_list

#===============================================================================
# This function returns the list of Anaplan workspaces a user may access as a
# JSON array
#===============================================================================
def get_workspaces(conn, user_id):
    '''
    @param conn: AnaplanConnection object which contains authorization string, workspace ID, and model ID
    @param user_id: 32-character string that uniquely identifies the Anaplan user
    '''
    
    url="https://api.anaplan.com/2/0/users/" + str(user_id) + "/workspaces"
    
    authorization = conn.authorization

    get_header = {
                "Authorization": authorization ,
                "Content-Type":"application/json"
                }
    
    logging.debug("Fetching workspaces...")
    
    workspace_list=requests.get(url, headers=get_header)
    workspace_list=json.loads(workspace_list.text)
    
    model_list=workspace_list["workspaces"]
    
    logging.debug("Finished fetching workspaces.")
    
    return model_list
    
#===============================================================================
# This function returns the action id based on the action name
#===============================================================================
def get_actionid(conn,action_type,action_name):
    '''
    @param conn: AnaplanConnection object which contains authorization string, workspace ID, and model ID
    @param action_type: string denoting action type
    @param action_name: string denoting action name
    '''
    list_of_actions = get_list(conn, action_type)
    actions_dict = anaplan_resource_dictionary.build_id_dict(list_of_actions,action_type)
    return anaplan_resource_dictionary.get_id(actions_dict,action_name)
    
#===============================================================================
# This function returns the file id based on the file name
#===============================================================================
def get_fileid(conn,file_name):
    '''
    @param conn: AnaplanConnection object which contains authorization string, workspace ID, and model ID
    @param file_name: string denoting file name
    '''
    list_of_files = get_list(conn, "files")
    files_dict = anaplan_resource_dictionary.build_id_dict(list_of_files,"files")
    return anaplan_resource_dictionary.get_id(files_dict, file_name)

#===============================================================================
# This function prints the http request object
#===============================================================================    
def pretty_print_request(req):
    """
    At this point it is completely built and ready
    to be fired; it is "prepared".

    However pay attention at the formatting used in 
    this function because it is programmed to be pretty 
    printed and may differ from the actual request.
    """
    logging.debug('{}\n{}\r\n{}\r\n\r\n{}'.format(
        '-----------START-----------',
        req.method + ' ' + req.url,
        '\r\n'.join('{}: {}'.format(k, v) for k, v in req.headers.items()),
        req.body,
    ))