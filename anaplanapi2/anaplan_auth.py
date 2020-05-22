#==============================================================================
# Created:        22 May 2019
# @author:        AP (adapated from Jesse Wilson)
# Description:	This script reads a user's public and private keys in order to
# 				sign a cryptographic nonce. It then generates a request to
# 				authenticate with Anaplan, passing the signed and unsigned
# 				nonces in the body of the request.
# Input:			Public certificate file location, private key file location
# Output:		Authorization header string, request body string containing a nonce and its signed value
#==============================================================================




#from M2Crypto import EVP, RSA

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric import utils

from base64 import b64encode
import requests
import json
import os
#import jks

#===============================================================================
# The private key must be RSA private key format
#===============================================================================

#===============================================================================
# This function fetches a key-pair from a Java keystore and prepares them for use
#===============================================================================
def get_keystore_pair(path, passphrase, alias, key_pass):
	'''
	@param path: Local path to the Java keystore where the keypair(s) are stored
	@param passphrase: Passphrase required to extract the keys from the keystore
	@param alias: Name of the key-pair to be used
	@param key_pass: Password to decrypt the keystore
	'''
	
	PRIVATE_BEGIN="-----BEGIN RSA PRIVATE KEY-----"
	PRIVATE_END="-----END RSA PRIVATE KEY-----"
	PUBLIC_BEGIN="-----BEGIN CERTIFICATE-----"
	PUBLIC_END="-----END CERTIFICATE-----"
"""
	ks=jks.KeyStore.load(path, passphrase)
	pk_entry=ks.private_keys[alias]

	if not pk_entry.is_decrypted():
		pk_entry.decrypt(key_pass)

	key=insert_newlines(b64encode(pk_entry.pkey_pkcs8).decode('utf-8'))
	cert=insert_newlines(b64encode(pk_entry.cert_chain[0][1]).decode('utf-8'))

	final_key='\n'.join([PRIVATE_BEGIN, key, PRIVATE_END])
	final_cert='\n'.join([PUBLIC_BEGIN, cert, PUBLIC_END])

	return final_key.encode('utf-8'), final_cert
"""

#===========================================================================
# This function converts base64 encoded private key and public certificate
# strings and splits them into 64-character lines so they can be read and
# handled correctly.
#===========================================================================
def insert_newlines(string, every=64):
	return '\n'.join(string[i:i+every] for i in range(0, len(string), every))

#===========================================================================
# This function reads a pseudo-randomly generated nonce and signs the text
# with the private key.
#===========================================================================
def sign_string(message, privKey):
	'''
	:param message: 150-character pseudo-random string of characters
	:param privKey: Path to private key, used to sign the nonce, or a bytes object containing the RSA private key
	'''
	if(isinstance(privKey, str)):
	#	key = RSA.load_key(privKey)
		with open(privKey, "rb") as key_file:
			key = serialization.load_pem_private_key(
				key_file.read(),
				password=None,
				backend=default_backend()
			)
	
	else:
		#key = RSA.load_key_string(privKey)
		key = serialization.load_pem_private_key(privKey,password=None,backend=default_backend())
	#md = EVP.MessageDigest('sha512')
	md = hashes.Hash(hashes.SHA512(), backend=default_backend())
	md.update(message)
	digest=md.finalize()
	
	#signature = key.sign(digest, "sha512")
	signature = key.sign(digest,
						padding.PSS(
							mgf=padding.MGF1(hashes.SHA512()),
							salt_length=padding.PSS.MAX_LENGTH
							),
						utils.Prehashed(hashes.SHA512())
						)
	
	return b64encode(signature).decode('utf-8')	

#===========================================================================
# The function generates a pseudo-random alpha-numeric 150 character nonce
# and returns the value
#===========================================================================
def create_nonce():
	randArr = os.urandom(150)
	
	return randArr
	
#===========================================================================
# This function takes a private key, calls the function to generate the nonce,
# then the function to sign the nonce, and finally returns the Anaplan authentication
# POST body value
#===========================================================================	
def generate_post_data(privKey):
	'''
	:param privKey: Path to private key
	'''
	
	unsigned_nonce=create_nonce()
	
	signed_nonce=str(sign_string(unsigned_nonce, privKey))
	json_string='{ "encodedData":"' + str(b64encode(unsigned_nonce).decode('utf-8')) + '", "encodedSignedData":"' + signed_nonce + '"}'

	return json_string

#===========================================================================
# This function reads a user's public certificate as a string, base64 
# encodes that value, then returns the certificate authorization header.
#===========================================================================
def certificate_auth_header(pubCert):
	'''
	:param pubCert: Path to public certificate
	'''
	
	if(pubCert[:5] == "-----"):
		my_pem_text=pubCert
	else:
		with open(pubCert, "r") as my_pem_file:
			my_pem_text = my_pem_file.read()
		
	header_string = { 'AUTHORIZATION':'CACertificate ' + b64encode(my_pem_text.encode('utf-8')).decode('utf-8') }
	
	return header_string

#===========================================================================
# This function takes in the Anaplan username and password, base64 encodes
# them, then returns the basic authorization header.
#===========================================================================
def basic_auth_header(username, password):
	'''
	:param username: Anaplan username
	:param password: Anaplan password
	'''
	
	header_string = { 'Authorization':'Basic ' + b64encode((username + ":" + password).encode('utf-8')).decode('utf-8') }
	return header_string

#===========================================================================
# This function takes the provided authorization header and POST body (if applicable),
# sends the authentication request to Anaplan, and returns the response as a string.
#===========================================================================
def auth_request(header, body):	
	'''
	:param header: Authorization type, CACertificate or Basic
	:param body: POST request body: encodedData (150-character nonce), encodedSignedData (encodedData value signed by private key)
	'''
	
	anaplan_url='https://auth.anaplan.com/token/authenticate'
	
	if body == None:
		r=requests.post(anaplan_url, headers=header)
	else:	
		r=requests.post(anaplan_url, headers=header, data=json.dumps(body))

	#Return the 	JSON array containing the authentication response, including AnaplanAuthToken
	return r.text

#===========================================================================
# This function reads the Anaplan auth token value and verifies its validity.
#===========================================================================
def verify_auth(token):	
	'''
	:param token: AnaplanAuthToken from authentication request.
	'''
	
	anaplan_url="https://auth.anaplan.com/token/validate"
	header = { "Authorization": "AnaplanAuthToken " + token }
	
	r=requests.get(anaplan_url, headers=header)
	
	status=json.loads(r.text)
	
	return status["statusMessage"]

#===========================================================================
# This function reads the string value of the JSON response for the Anaplan
# authentication request. If the login was successful, it verifies the token,
# then returns the Authorization header for the API. If unsuccessful, it returns
# the error message.
#===========================================================================
def authenticate(response):	
	'''
	:param response: JSON array of authentication request
	'''
	
	json_response = json.loads(response)
	#Check that the request was successful, is so extract the AnaplanAuthToken value 
	if not json_response["status"] == "FAILURE_BAD_CREDENTIAL":
		token = json_response["tokenInfo"]["tokenValue"]
		status = verify_auth(token)
		if status == 'Token validated':
			return "AnaplanAuthToken " + token
		else:
			return "Error: " + status
	else:
		status = "Error: " + json_response["statusMessage"]
		return status

#===========================================================================
# This function takes in the current token value, refreshes, and returns the
# updated token Authorization header value.
#===========================================================================
def refresh_token(token):	
	'''
	@param token: Token value that is nearing expiry 
	'''
	
	url="https://auth.anaplan.com/token/refresh"
	header={ "Authorization" : "AnaplanAuthToken " + token }
	r = requests.post(url, headers=header)
	
	new_token=json.loads(r.text)["tokenInfo"]["tokenValue"]
	
	return "AnaplanAuthToken " + new_token