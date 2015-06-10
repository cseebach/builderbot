import configparser
import argparse
import json

import dropbox

parser = argparse.ArgumentParser()
parser.add_argument("config_path")
args = parser.parse_args()

config = configparser.ConfigParser()
config.read(args.config_path)

# Get your app key and secret from the Dropbox developer website
app_key = config["dropbox"]["key"]
app_secret = config["dropbox"]["secret"]

flow = dropbox.client.DropboxOAuth2FlowNoRedirect(app_key, app_secret)

# Have the user sign in and authorize this token
authorize_url = flow.start()
print('1. Go to: ' + authorize_url)
print('2. Click "Allow" (you might have to log in first)')
print('3. Copy the authorization code.')
code = input("Enter the authorization code here: ").strip()

# This will fail if the user enters an invalid authorization code
access_token, user_id = flow.finish(code)

token = {
    "access_token":access_token,
    "user_id":user_id,
}

with open(config["paths"]["authorization"], "w") as auth_file:
    json.dump(token, auth_file)
