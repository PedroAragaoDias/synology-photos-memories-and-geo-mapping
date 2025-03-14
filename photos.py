from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, jsonify, render_template, request, redirect, url_for, Response
from urllib.parse import urlencode, quote
from time import localtime, strftime
from dotenv import load_dotenv

from datetime import datetime
from jinja2 import Environment, FileSystemLoader

import logging
import urllib3
import requests
import os
import subprocess
import time
import threading
import re
import json

# Memories
import math
import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)  # Suppress SSL warnings

all_folders, all_photos, all_photos_with_gps, all_memories_photos = {}, {}, {}, {}
last_memories_build_date = None
full_refresh_required = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__, static_folder='static')

# Flask port
flaskPort = int(os.getenv("FLASK_PORT"))

# General settings
nasUser = os.getenv("NAS_USER_ID")
nasPassword = os.getenv("NAS_USER_PASSWORD")
nasInternalPhotoHost = os.getenv("NAS_INTERNAL_PHOTO_HOST")
nasExternalPhotoHost = os.getenv("NAS_EXTERNAL_PHOTO_HOST")
nasExternalContainerHost = os.getenv("NAS_EXTERNAL_CONTAINER_HOST")
fotoSpace = "FotoTeam" if os.getenv("FOTO_TEAM") == "true" else "Foto"

# Photos settings
rebuildHour = int(os.getenv("REBUILD_HOUR"))
exclude_folders_ids = json.loads(os.getenv("EXCLUDE_FOLDERS_IDS", "[]"))
exclude_folders_names = json.loads(os.getenv("EXCLUDE_FOLDERS_NAMES", "[]"))

# Avoid Cross-Origin Resource Sharing (CORS) restrictions! The last "/" is needed!!
#converterUrl = os.getenv("CONVERTER_URL")
# Getting photos during zoom abandoned. It gave too many errors while navigating thru the photos because browsing thru them triggers zooming and unwanted recalculations
#visibleThreshold = int(os.getenv("VISIBBLE_PLACEHOLDERS_THRESOLD"))

# Memories settings
send_email_by = os.getenv("SEND_EMAIL_BY")
send_email_service = os.getenv("SEND_EMAIL_SERVICE")
send_email_service_port = int(os.getenv("SEND_EMAIL_SERVICE_PORT"))
send_email_from = os.getenv("SEND_EMAIL_FROM")
send_email_password = os.getenv("SEND_EMAIL_PASSWORD")
send_email_to = os.getenv("SEND_EMAIL_TO").split(",")
send_email_subject = os.getenv("SEND_EMAIL_SUBJECT")
send_email_max_photos = int(os.getenv("SEND_EMAIL_MAX_PHOTOS"))
send_email_photo_mozaic_row_max_width = int(os.getenv("SEND_EMAIL_PHOTO_MOZAIC_ROW_MAX_WIDTH"))
send_email_photo_mozaic_height = int(os.getenv("SEND_EMAIL_PHOTO_MOZAIC_HEIGHT"))

MAP_CONTEXT = "Map"
BROWSE_CONTEXT = "Browse"
MEMORIES_CONTEXT = "Memories"

########################################################################################################################################################################################################
# Generic API methods
########################################################################################################################################################################################################

def call_api(cgi, params):
    api_url = f"{nasInternalPhotoHost}/webapi/{cgi}.cgi"
    
    #logging.info(f"Calling API {api_url} with {params}")
    
    apiResult = requests.get(api_url, params=params, verify=False)
    
    #logging.info(f"API call ended! Result: {apiResult}")
    
    return apiResult

def login():
    """Get the session token (API key) from Synology DSM."""
    logging.info(f"Authenticating...")
    
    try:
        response = call_api("auth", {"api": "SYNO.API.Auth", "version": 7, "method": "login", "account": nasUser, "passwd": nasPassword, "session": "photo", "format": "sid"})
    except Exception as e:
        logging.info(f"Login Error! {e}")
        raise Exception(f"Failed to call authentication API! Error: {e}")
    
    data = response.json()
    
    logging.info(f"Authenticatied! {data}")

    if response.status_code == 200:
        if data["success"]:
            return data["data"]["sid"]  # Return session ID (API Key)
        else:
            raise Exception("Failed to authenticate with DSM")
    else:
        raise Exception(f"Error while getting session token: {response.status_code}")

def logout():
    logging.info(f"Logging out...")
    
    response = call_api("auth", {"api": "SYNO.API.Auth", "version": 6, "method": "logout"})
    
    data = response.json()
    
    logging.info(f"Logged out! {data}")

    if response.status_code != 200:
        raise Exception(f"Error while logging out: {response.status_code}")

def get_api_info(api):
    response = call_api("query", {"api": "SYNO.API.Info", "version": 1, "method": "query", "query": f"{api}"})
    logging.info(f"{api} Version: {response.json()}")

def get_cached_folder_name_for_item(sid, item):
    global all_folders

    folder_id = item["folder_id"]

    #logging.info(f"Searching folder for {item} in {all_folders}")

    # Search for the folder with the specific ID
    #folder = next((f for f in all_folders if f.get("id") == folder_id), None)
    folder = None
    if folder_id in all_folders:
        folder = all_folders[folder_id]
    
    if folder:
        #logging.info(f"Folder {folder_id} found in cache!! {folder}")
        return folder["name"]
    else:
        # Folder not yet cached, getting and caching..
        folder_name = get_folder_name(sid, folder_id)

        #logging.info(f"Folder {folder_id} not found in cache. Caching it!! {folder}")
        #all_folders.append(folder)
        all_folders[folder_id] = { "name" : folder_name }
        return folder_name

def get_folder_name(sid, folder_id):
    #logging.info(f"Getting folder_id {folder_id}...")
    
    # Request a batch of folders
    response = call_api("entry", {"api": f"SYNO.{fotoSpace}.Browse.Folder", "version": 2, "method": "get", "_sid": sid, "id": folder_id, "offset": 0, "limit": 1})
    if response.status_code != 200:
        raise Exception(f"Error requesting folder {folder_id}: {response.status_code}, {response.text}")

    # Extract folder list
    folder = response.json()
    return folder["data"]["folder"]["name"]

def cache_root_folders_names(sid):

    # Debug...
    #return
    # ...Debug
    
    logging.info(f"Getting folders...")
    
    global all_folders

    # Step 1: Fetch all photos in the current folder (handle pagination)
    offset = 0
    limit = 1000  # Set a reasonable limit for each request
    while True:
        # Request a batch of folders
        response = call_api("entry", {"api": f"SYNO.{fotoSpace}.Browse.Folder", "version": 2, "method": "list", "_sid": sid, "offset": 0, "limit": 1000})
        if response.status_code != 200:
            raise Exception(f"Error requesting folder {folder_id}: {response.status_code}, {response.text}")

        # Extract folder list
        data = response.json()

        if data["success"]:
            # Collect photos with GPS data
            root_folders = data["data"]["list"]

            for folder in root_folders:
                folder_id = folder["id"]
                # If photo already in cache and it's in the same folder as initialy detected, skip it
                #if folder_id in all_folders and all_folders[folder_id]["name"] == folder["name"]:
                #    continue
                all_folders[folder_id] = {"name": folder["name"]}

            if len(root_folders) < limit:
                break  # Exit the loop if we fetched the last page
            offset += limit  # Increment offset for the next page
            
    logging.info(f"Folders found: {len(all_folders)}")

def fetch_all_photos(sid):
    """
    Fetch photos with GPS data from Synology Photos API recursively.
    Handles pagination and traverses all subfolders.
    :param sid: Session ID (API Key)    
    :return: List of photos with GPS data
    """

    logging.info(f"Fetching photos...")

    global all_photos, all_photos_with_gps
    
    # Release...
    cache_root_folders_names(sid)

    # Step 1: Fetch all photos in the current folder (handle pagination)
    offset = 0
    limit = 2500  # Set a reasonable limit for each request
    while True:
        #logging.info(f"Getting photos...: {photos_url} , folder_params: {folder_params}")
        # Some dont seem to work. Maybe some of them can only be requested to videos and others to photos?! The bellow one where captured from "Synology Photos Web Site"
        # "additional": "[\"description\",\"tag\",\"exif\",\"resolution\",\"orientation\",\"gps\",\"video_meta\",\"video_convert\",\"thumbnail\",\"address\",\"geocoding_id\",\"rating\",\"motion_photo\",\"person\"]"
        response = call_api("entry", {"api": f"SYNO.{fotoSpace}.Browse.Item", "version": 6, "method": "list", "_sid": sid, "additional": "[\"thumbnail\",\"gps\",\"resolution\",\"exif\",\"description\",\"tag\",\"orientation\",\"video_meta\",\"video_convert\",\"address\",\"geocoding_id\",\"rating\",\"motion_photo\",\"person\"]", "offset": offset, "limit": limit})

        #logging.info(f"Photos: {response.json()}")

        if response.status_code == 200:

            #logging.info(f"Status: {response.status_code}")

            data = response.json()
            if data["success"]:
                # Collect photos with GPS data
                photos = data["data"]["list"]

                #logging.info(f"Success! Photos found: {len(photos)}")

                for photo in photos:
                    id_val=photo["id"]

                    # If photo already in cache and it's in the same folder as initialy detected, skip it
                    if id_val in all_photos and all_photos[id_val]['photo_data']['original']["folder_id"] == photo["folder_id"]:
                        continue

                    thumbnail_url = get_thumbnail_url(sid, photo)
                    watch_url = get_watch_url(sid, photo)
                    download_url = get_download_url(sid, photo)

                    # If there is no gps data and its a non avi video, try to add the geo location metadata
                    if not photo.get("additional").get("gps"):
                        if photo['type'] == "video" and get_mime_type(photo['filename']) != "video/avi":
                            video_geodata = get_video_geodata(download_url)
                            if video_geodata is not None and video_geodata['latitude'] != 0 and video_geodata['longitude'] != 0:
                                photo.setdefault('additional', {}).setdefault('gps', {})
                                photo['additional']['gps']['latitude'] = video_geodata['latitude']
                                photo['additional']['gps']['longitude'] = video_geodata['longitude']
                                #logging.info(f"Found and adding video GPS metadata for: {photo}")
                                
                                # TODO: Would it be possible to set this gps position in the synology database? Will the Synology system overwrite it afterwards?!

                    folder_name = get_cached_folder_name_for_item(sid, photo).lstrip("/")

                    timeStr = strftime('%Y/%m/%d %H:%M:%S', localtime(photo["time"]))

                    tooltip = { 'Date': timeStr, f"Name ({id_val})": f"{photo['filename']} ({photo['filesize'] / (1024 * 1024):.2f} MB)", f"Folder ({photo['folder_id']})": folder_name }
                    if (photo.get("additional").get("resolution")):
                        tooltip['Dimension'] = f"{photo['additional']['resolution']['width']}x{photo['additional']['resolution']['height']}"
                    if photo.get("additional").get("gps"):
                        tooltip['Location'] = f"{photo['additional']['gps']['latitude']}, {photo['additional']['gps']['longitude']}"

                    exif = ""
                    if photo.get("additional").get("exif"):
                        camera = photo.get("additional").get("exif").get("camera")
                        if camera and camera.strip():
                            exif += (", " if exif else "") + camera
                        aperture = photo.get("additional").get("exif").get("aperture")
                        if aperture and aperture.strip():
                            exif += (", " if exif else "") + aperture
                        exposure = photo.get("additional").get("exif").get("exposure_time")
                        if exposure and exposure.strip():
                            exif += (", " if exif else "") + exposure
                        focal = photo.get("additional").get("exif").get("focal_length")
                        if focal and focal.strip():
                            exif += (", " if exif else "") + focal
                        iso = photo.get("additional").get("exif").get("iso")
                        if iso and iso.strip():
                            exif += (", " if exif else "") + f"{iso} iso"
                        lens = photo.get("additional").get("exif").get("lens")
                        if lens and lens.strip():
                            exif += (", " if exif else "") + lens
                        if exif and exif.strip():
                            tooltip['Camera'] = exif

                    photo_extended = {
                        "folder_name": folder_name,
                        "timeStr" : timeStr, 
                        "thumbnail_url": thumbnail_url,
                        "watch_url": watch_url,
                        "download_url": download_url,
                        "tooltip" : tooltip,
                        "original": photo
                    }

                    if photo_extended['original']['folder_id'] not in exclude_folders_ids or folder_name not in exclude_folders_names:

                        ## TODO: Debug... 
                        #if photo_extended['original']['type'] == "video":
                        #    all_photos[id_val] = { "photo_data" : photo_extended }
                        #if photo_extended['original']['additional'].get("gps"):
                        #    logging.info(f"Adding GPS photo {len(all_photos)}/{len(all_photos_with_gps)} photo: {id_val}: {photo_extended}")
                        #        all_photos_with_gps[id_val] = { "photo_data" : photo_extended }
                        #else:    
                        #   logging.info(f"Adding non GPS {len(all_photos)}/{len(all_photos_with_gps)} photo: {id_val}: {photo_extended}")
                        #if len(all_photos) >= 500:
                        #    break
                        ## TODO: ...Debug

                        # TODO: Release... 
                        all_photos[id_val] = { "photo_data" : photo_extended }
                        if photo_extended['original']['additional'].get("gps"):
                            all_photos_with_gps[id_val] = { "photo_data" : photo_extended }
                        # TODO: ...Release

                        # It should not create a new line, but it is...
                        #logging.info(f"\rAdded new photo {len(all_photos)}/{len(all_photos_with_gps)}...")

                ## TODO: Debug... 
                #break
                ## TODO: ...Debug
                
                if len(photos) < limit:
                    break  # Exit the loop if we fetched the last page
                offset += limit  # Increment offset for the next page
            else:
                raise Exception(f"Failed to list photos: {data}")
        else:
            raise Exception(f"Error fetching photos: {response}")

    logging.info(f"Found photos {len(all_photos)} photos found (with GPS data: {len(all_photos_with_gps)})!")

########################################################################################################################################################################################################
# Generic methods
########################################################################################################################################################################################################

def get_html_email(sid, photos):
    num_photos = 0
    num_videos = 0
    
    last_date = ""
    new_date_tag = ""
    row_photo_row_tag = ""
    current_photo_mozaic_row_width = 0
    current_photo = 0
    changed_date = False
    
    photos_urls_rows = []
    for photo in photos.values():
        current_photo += 1
        
        photo_data = photo['photo_data']
        original_photo = photo_data['original']
        time = original_photo['time']
        
        taken_date = datetime.fromtimestamp(time)
        
        formatted_date = taken_date.strftime('%d/%m/%Y')
        formatted_time = taken_date.strftime('%H:%M:%S')

        thumbnail_url = get_thumbnail_url(sid, original_photo)
        link_text = f"{formatted_date} {formatted_time}"

        if last_date != formatted_date:
            changed_date = True
        
        if changed_date:
            last_date = formatted_date
            current_photo_mozaic_row_width = 0
            
            if current_photo != 1:
                new_date_tag = "</td></tr><br>"
            
            new_date_tag += f'<tr valign="middle" width="100%" align="center"><td valign="middle" align="center"><strong align="center" width="100%" style="font-size:13px;color:#FFFFFF">📌  {formatted_date}</strong>'
        else:
            new_date_tag = ""
        
        photo_width_adjusted = int(original_photo['additional']['resolution']['width'] * send_email_photo_mozaic_height / original_photo['additional']['resolution']['height'])
        photo_height_adjusted = send_email_photo_mozaic_height
        
        photo_width_adjusted_warning = ""
        if photo_width_adjusted == 0:
            photo_width_adjusted_warning = "WARNING: Unable to determine photo rectangle!!\n"
            photo_width_adjusted = send_email_photo_mozaic_height
        
        if (current_photo_mozaic_row_width + photo_width_adjusted > send_email_photo_mozaic_row_max_width) or changed_date:
            changed_date = False
            
            if current_photo != 1:
                row_photo_row_tag = "</td></tr>"
            row_photo_row_tag += '<tr style="background-color:#000000;color:#FFFFFF;" valign="middle" width="100%" align="center"><td valign="middle" width="100%" align="center">'
            
            current_photo_mozaic_row_width = photo_width_adjusted
        else:
            row_photo_row_tag = ""
            current_photo_mozaic_row_width += photo_width_adjusted
        
        if original_photo['type'] == 'photo':
            num_photos += 1
            html_tag = f'<img valign="middle" src="{thumbnail_url}" width="{photo_width_adjusted}px" height="{photo_height_adjusted}px" style="border: #FFFFFF 2px outset;" />'
        else:
            num_videos += 1
            html_tag = f'''
            <table align="center" valign="middle" style="background-color:#0000FF; display: inline-block;">
                <tr>
                    <td width="{photo_width_adjusted}px" height="{photo_height_adjusted}px" background="{thumbnail_url}" style="background-position: center center; background-size:cover; background-repeat: no-repeat;">
                        <div>
                            <table role="presentation" cellpadding="0" cellspacing="0" align="center" height="100%" width="100%">
                                <tr>
                                    <td align="center" valign="middle">
                                        <img src="{nasExternalContainerHost}/static/images/play.png" height="30px" width="30px" />
                                    </td>
                                </tr>
                            </table>
                        </div>
                    </td>
                </tr>
            </table>'''
        
        href_tag = f"{nasExternalContainerHost}/static/pages/photo.html?photo_id={original_photo['id']}&context={MEMORIES_CONTEXT}"

        latitude = original_photo['additional']['gps']['latitude'] if 'gps' in original_photo['additional'] else "N/A"
        longitude = original_photo['additional']['gps']['longitude'] if 'gps' in original_photo['additional'] else "N/A"
        
        photos_urls_rows.append(f'{new_date_tag}{row_photo_row_tag}<a href="{href_tag}" target="_blank"><span title="{photo_width_adjusted_warning}Date: {formatted_date} {formatted_time}\nName ({original_photo["id"]}): {original_photo["filename"]}\nSize: {original_photo["filesize"]}\nFolder ({original_photo["folder_id"]}): {photo_data["folder_name"]}\nType: {original_photo["type"]}\nWidth: {original_photo["additional"]["resolution"]["width"]}\nHeight: {original_photo["additional"]["resolution"]["height"]}\nLatitude: {latitude}\nLongitude: {longitude}\n">{html_tag}</span></a>&nbsp;')
    
    return [f'<table width="100%" align="center" style="background-color:#000000;"><tr><td valign="middle" align="center"><a href="{nasExternalContainerHost}/memories"><strong align="center" width="100%" style="font-size:13px;color:#FFFFFF">Web Version</strong></a></td></tr>' + ''.join(photos_urls_rows) + '</table>', num_photos, num_videos]

def send_result_email(sid, photos, send_email_service, send_email_service_port, send_email_from, send_email_to, send_email_subject, send_email_password):
    html_content, num_photos, num_videos = get_html_email(sid, photos)

    # Check if photoUrls is empty
    if num_photos + num_videos > 0:
        logging.info(f"Sending {num_photos} photo(s) and {num_videos} video(s) thru {send_email_service}:{send_email_service_port} to {send_email_to} (using {send_email_from} and {send_email_password})")
        subject_suffix = f" - {num_photos} photo(s) and {num_videos} video(s)"
        mail_html = html_content
    else:
        logging.info(f"No photos to send found! Sending information mail thru {send_email_service}:{send_email_service_port}, to {send_email_to} (using {send_email_from} and {send_email_password})")
        subject_suffix = ' - No photos to send found!'
        mail_html = "<B>No photos to send found!</B>"

    # Setup the MIME
    message = MIMEMultipart()
    message['From'] = send_email_from
    message['To'] = ", ".join(send_email_to)  # Convert list to comma-separated string
    message['Subject'] = send_email_subject + subject_suffix

    # Attach HTML content
    message.attach(MIMEText(mail_html, 'html'))

    # Sending the email
    try:
        with smtplib.SMTP(send_email_service, send_email_service_port) as server:
            server.starttls()  # Secure the connection
            server.login(send_email_from, send_email_password)
            server.sendmail(send_email_from, send_email_to, message.as_string())
            logging.info(f"Email sent thru {send_email_service}:{send_email_service_port}, to {send_email_to} (using {send_email_from} and {send_email_password})")
    except Exception as e:
        logging.info(f"Error sending mail thru {send_email_service}:{send_email_service_port}, to {send_email_to} (using {send_email_from} and {send_email_password}): {e}")

# Get video metadata
def get_video_geodata(video_url):
    #logging.info(f"Getting video metadata for {video_url}")

    # Create ffmpeg command
    command = [
        'ffmpeg',
        '-i', video_url,        # Pass the URL directly to ffmpeg
        '-loglevel', 'error',   # Only output errors
        '-f', 'ffmetadata',     # Request metadata
        '-',                # Does not write output to a file but only to stdout
    ]

    # Start the FFmpeg process and capture stdout & stderr
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,   # Capture standard output
        stderr=subprocess.PIPE,   # Capture standard error
        text=True                 # Ensures output is in string format (Python 3.7+)
    )

    # Wait for the process to complete and capture output
    stdout, stderr = process.communicate()

    # Log the return code
    #logging.info(f"ffmpeg process finished with return code {process.returncode}")

    # Print or process the captured output
    stdout_str = stdout.strip()
    stderr_str = stderr.strip()
    #logging.info(f"ffmpeg metadata stdout: {stdout_str}")
    #logging.info(f"ffmpeg metadata stderr: {stderr_str}")

    if process.returncode != 0:
        return None

    # Regular expression to find latitude and longitude in any line
    match = re.search(r"location=[+]?(-?\d+\.\d+)([+-]\d+\.\d+)/", stdout_str)

    if match:
        latitude = float(match.group(1))
        longitude = float(match.group(2))
        #logging.info(f"Found Latitude: {latitude}, Longitude: {longitude}")
        return { "latitude": latitude, "longitude" : longitude }
        
    return None

# Dictionary to map file extensions to MIME types
mime_types = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".avi": "video/avi"
}

# Function to get the MIME type based on the file extension
def get_mime_type(file_name):
    extension = file_name[file_name.rfind('.'):].lower()
    return mime_types.get(extension, "application/octet-stream")

# To force the download use: download_type=source&force_download=true
def get_download_url(sid, photo):
    return f"{nasExternalPhotoHost}/webapi/entry.cgi?api=SYNO.{fotoSpace}.Download&version=2&method=download&unit_id=[{photo['id']}]&_sid={sid}"

def get_watch_url(sid, photo):
    # If video and it needs transcoding, return stream link
    if get_mime_type(photo['filename']) == "video/avi":
        return f"{nasExternalPhotoHost}/webapi/entry.cgi?api=SYNO.{fotoSpace}.Streaming&version=2&method=streaming&type=item&id={photo['id']}&quality=medium&_sid={sid}"
    else:
        return get_download_url(sid, photo)

# Only with small size...
#def get_thumbnail_url(sid, photo):
#    # Check if the "thumbnail" key exists in the "additional" dictionary
#    if photo.get("additional").get("thumbnail").get("url"):
#        return photo["additional"]["thumbnail"]["url"]
#    else:
#        return f"{nasExternalPhotoHost}/webapi/entry.cgi?api=SYNO.{fotoSpace}.Thumbnail&version=2&method=get&mode=download&id={photo['id']}&type=unit&size=sm&cache_key={photo['additional']['thumbnail']['cache_key']}&_sid={sid}"
def get_thumbnail_url(sid, photo):
    # Check if the "thumbnail" key exists in the "additional" dictionary
    if photo.get("additional").get("thumbnail").get("url"):
        return photo["additional"]["thumbnail"]["url"]
    else:
        maxThumbnailSize = "xl" # default if fails
        if photo["additional"]["thumbnail"]["xl"] == "ready":
            maxThumbnailSize = "xl"
        elif photo["additional"]["thumbnail"]["m"] == "ready":
            maxThumbnailSize = "m"
        elif photo["additional"]["thumbnail"]["sm"] == "ready":
            maxThumbnailSize = "sm"
        elif photo["additional"]["thumbnail"]["preview"] == "ready":
            maxThumbnailSize = "preview"
        return f"{nasExternalPhotoHost}/webapi/entry.cgi?api=SYNO.{fotoSpace}.Thumbnail&version=2&method=get&mode=download&id={photo['id']}&type=unit&size={maxThumbnailSize}&cache_key={photo['additional']['thumbnail']['cache_key']}&_sid={sid}"

########################################################################################################################################################################################################
# Memories methods
########################################################################################################################################################################################################

def filter_photos_by_month(photos, month):
    current_year = datetime.now().year

    logging.info(f"Returning photos where taken_date.month == {month} and taken_date.year < {current_year}")

    return { photo_id: photo for photo_id, photo in photos.items() if (taken_date := datetime.fromtimestamp(photo['time'])).month == month and taken_date.year < current_year }

def get_week_number(date):
    first_day_of_year = datetime(date.year, 1, 1)
    past_days_of_year = (date - first_day_of_year).days + 1  # Include the current day
    return ((past_days_of_year + first_day_of_year.weekday()) // 7) + 1

def filter_photos_by_week(photos, week):
    current_year = datetime.now().year

    logging.info(f"Returning photos where get_week_number(taken_date) == {week} and taken_date.year < {current_year}")

    return { photo_id: photo for photo_id, photo in photos.items() if get_week_number(taken_date := datetime.fromtimestamp(photo['time'])) == week and taken_date.year < current_year }


def filter_photos_by_day(photos, day, month):
    current_year = datetime.now().year

    logging.info(f"Returning photos where taken_date.day == {day} and taken_date.month == {month} and taken_date.year < {current_year}")

    return { photo_id: photo for photo_id, photo in photos.items() if (taken_date := datetime.fromtimestamp(photo['photo_data']['original']['time'])).day == day and taken_date.month == month and taken_date.year < current_year }

def get_random_memories_photos(photos, max_photos):
    # Convert dictionary keys to a list (without sorting)
    photo_ids = list(photos.keys())  
    total_photos = len(photo_ids)

    # Determine the number of photos to select
    email_adjusted_max_photos = total_photos if max_photos == 0 else max_photos
    real_max_photos = min(email_adjusted_max_photos, total_photos)

    if real_max_photos == 0:  # Avoid division by zero
        return {}

    photo_step = total_photos / real_max_photos
    random_memories_photos = {}

    for i in range(real_max_photos):
        random_index = math.floor((i + 1) * photo_step) - 1
        random_index = max(0, min(random_index, total_photos - 1))  # Ensure valid index
        selected_photo_id = photo_ids[random_index]  # Get actual dictionary key

        #logging.info(f"Adding {photos[selected_photo_id]['photo_data']['original']['type']} to memories index {i}: {photos[selected_photo_id]}")
        
        random_memories_photos[selected_photo_id] = photos[selected_photo_id]  # Maintain original structure

    return random_memories_photos

########################################################################################################################################################################################################
# Photos Map methods
########################################################################################################################################################################################################
app = Flask(__name__)

# Add required headers to every response
#@app.after_request
#def add_security_headers(response):
#    response.headers["Cross-Origin-Embedder-Policy"] = "require-corp"
#    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
#    return response

@app.route('/convert/<path:url>', methods=['GET'])
def converter(url):
    # Get query parameters from the request (including the byte range if present)
    query_params = request.args.to_dict()

    logging.info(f"Routing {request.path}: {url}, {query_params}")

    #logging.info(f"Converter url: {url}, parameters: {query_params}")
    #logging.info(f"Headers: {request.headers}")

    # Clean up any potential range values in the query string
    for key, value in query_params.items():
        if isinstance(value, str) and '?' in value:
            # Split off the range if it's included in the value
            base_value, *range_part = value.split('?')
            #if range_part:
            #    app.logger.info(f"Removing byte range from parameter '{key}': {range_part[0]}")
            query_params[key] = base_value

    # Reconstruct the URL without the byte range (and other params if needed)
    if query_params:
        video_url = f"{url}?{urlencode(query_params)}"
    else:
        video_url = url
    video_url = quote(video_url, safe=":/?&=%")
    logging.info(f"Retrieving {video_url}")

    # Start the FFmpeg process...
    command = [
        'ffmpeg',
        '-i', video_url,  # Pass the URL directly to ffmpeg
        '-vcodec', 'libx264',  # Transcode to H.264 video codec
        '-acodec', 'aac',  # Transcode to AAC audio codec
        '-movflags', 'frag_keyframe+empty_moov+faststart',  # 
        '-f', 'mp4',  # Output as MP4
        'pipe:1'  # Output goes to the standard output (piped data)
    ]

    logging.info(f"Creating command  {command}")

    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    logging.info(f"Process created")

    def log_stderr(pipe):
        logging.info("Reading...")
        transcode_progress = 0

        try:
            for line in iter(pipe.readline, b''):
                line = line.decode('utf-8', errors='replace').strip()

                if line:
                    logging.info(f"[ffmpeg pipe]: {line}")

                    if "frame=" in line and "fps=" in line:
                        transcode_progress += 1
                        logging.info(f"Transcoding Progress: {line.strip()}")
        except Exception as e:
            logging.error(f"Pipe closed?! {e}")

    stderr_thread = threading.Thread(target=log_stderr, args=(process.stderr, ))
    stderr_thread.start()

    #####
    ##### Download blocks version: 
    #####
    #####import sys
    #####def generate_old_from_file():
    #####    logging.info(f"Generating..")
    #####    
    #####    download_progress = 0
    #####    transcode_progress = 0
    #####    start_time = time.time()
    #####
    #####    for chunk in video_stream.iter_content(chunk_size=1024):
    #####        logging.info(f"Chunk {len(chunk)}: {chunk[:75]}")
    #####        
    #####        # Write the video data to FFmpeg's input
    #####        process.stdin.write(chunk)
    #####        process.stdin.flush()
    #####
    #####        logging.info(f"Yield {len(chunk)}: {chunk[:75]}")
    #####        
    #####        # Yield transcoded data to the client
    #####        yield process.stdout.read(1024)
    #####
    #####        logging.info(f"Yield!")
    #####
    #####        # Log download progress
    #####        download_progress += len(chunk)
    #####        elapsed_time = time.time() - start_time
    #####
    #####        logging.log(f"Download Progress: {download_progress} bytes | Time Elapsed: {elapsed_time:.2f}s", file=sys.stderr)
    #####
    #####    # Wait for the process to complete
    #####    process.stdin.close()
    #####    process.wait()
    #####
    #####    # Log the return code
    #####    logging.info(f"ffmpeg process finished with return code {process.returncode}")
    #####
    #####    # Log any remaining output from stdout and stderr
    #####    stdout, stderr = process.communicate()
    #####    if stdout:
    #####        logging.info(f"[ffmpeg stdout]: {stdout.decode('utf-8', errors='replace').strip()}")
    #####    if stderr:
    #####        logging.info(f"[ffmpeg stderr]: {stderr.decode('utf-8', errors='replace').strip()}")
    #####
    #####    # Function to generate the response
    def generate():
        while True:
            output = process.stdout.read(1024)
            if not output:
                break

            #logging.info(f"Yield {len(output)}: {output[:75]}")
            yield output

        # Wait for the process to complete
        process.wait()

        # Log the return code
        logging.info(f"ffmpeg process finished with return code {process.returncode}")

        # Log any remaining output from stdout and stderr
        stdout, stderr = process.communicate()
        if stdout:
            logging.info(f"[ffmpeg stdout (final)]: {stdout.decode('utf-8', errors='replace').strip()}")
        if stderr:
            logging.info(f"[ffmpeg stderr (final)]: {stderr.decode('utf-8', errors='replace').strip()}")

    logging.info(f"Routed {request.path}: {url}, {query_params}")

    return Response(generate(), content_type='video/mp4')

@app.route('/proxy/<path:url>', methods=['GET'])
def proxy(url):
    logging.info("Routing %s: url: %s, args: %s", request.path, url, request.args)

    # Extract query parameters
    query_params = request.query_string.decode('utf-8')
    
    # Construct the new URL
    new_url = url
    if query_params:
        new_url += f"?{query_params}"
    
    logging.info("Redirecting to %s", new_url)
    
    # Forward the request to the target URL
    response = requests.get(new_url)
    
    # Create a new response with the same content and status code
    return Response(response.content, status=response.status_code, headers=dict(response.headers))
    
# Define a route to return a photo at a specified offset position
@app.route('/photo_id', methods=['GET'])
def get_photo_id():
    logging.info("Routing %s/%s (%d, %d, %d)", request.path, request.args, len(all_photos), len(all_photos_with_gps), len(all_memories_photos))

    photoId = int(request.args.get("id"))
    offSet = request.args.get("offSet")
    context = request.args.get("context")

    try:
        offSet = int(offSet)  # Convert to integer
    except ValueError:
        offSet = 0

    if context and context==MAP_CONTEXT:
        photos_to_consider = all_photos_with_gps
    elif context and context==MEMORIES_CONTEXT:
        photos_to_consider = all_memories_photos
    else: # BROWSE_CONTEXT or anything else...
        photos_to_consider = all_photos

    if not isinstance(photos_to_consider, dict) or len(photos_to_consider) == 0:
        logging.info("Error routing %s/%s: Photo and video data not initialized yet or unexistent!", request.path, request.args)
        return jsonify({"Error": "Photo and video data not initialized yet or unexistent!"}), 500

    # Wrap around if the offset is out of bounds
    try:
        photoIdIndex = list(photos_to_consider.keys()).index(photoId)
    except ValueError:
        logging.info("Error routing %s/%s: Photo or video not found in the requested context! (the cache was rebuilt?!)", request.path, request.args)
        return jsonify({"Photo or video not found in the requested context and offset! (was the cache rebuilt?!)"}), 500
        
    newPhotoIndex = ((photoIdIndex + offSet) % len(photos_to_consider) + len(photos_to_consider)) % len(photos_to_consider)

    #logging.info("photoIdIndex: %d, newPhotoIndex: %d", photoIdIndex, newPhotoIndex)

    found_photo = list(photos_to_consider.values())[newPhotoIndex]["photo_data"]
    
    #logging.info(f"Routed {request.path}/{request.args} and returning photo {found_photo[photo_date][id]}: {found_photo}")

    if found_photo is None:
        logging.info("Error routing %s/%s: Photo or video not found in the requested context and offset!", request.path, request.args)
        return jsonify({"Photo or video not found in the requested context and offset!"}), 400
        
    # Return the photo at the calculated offSet
    return jsonify(found_photo)

# Send email with memories mosaic and build the html memories page
def build_memories_and_send_email(sid, date, send_email, thread = None):
    # Wait for the rebuild cache thread?!
    if thread is not None:
        thread.join()  # Wait for the thread to finish
    
    global all_memories_photos
    global last_memories_build_date

    if date is None:
        date = datetime.now() 

    day = date.day
    week = get_week_number(date)
    month = date.month

    rebuild_memories = True

    if len(all_memories_photos) > 0 and last_memories_build_date is not None:
        logging.info(f"Testing last rebuid date: Requested Day {day} vs {last_memories_build_date.day}, Week {week} vs {get_week_number(last_memories_build_date)} and Month {month} vs {last_memories_build_date.month})")

        # Return last build photos
        if (day == last_memories_build_date.day and week == get_week_number(last_memories_build_date) and month == (last_memories_build_date.month)):
            logging.info(f"Using {send_email_by} photos array cache! No need to build! (requested day {day}, week {week}, month {month})")
            rebuild_memories = False

    if rebuild_memories: 
        logging.info(f"Building {send_email_by} photos array...(last build day N/A, week N/A, month N/A (requested day {day}, week {week}, month {month})")
        
        # Photos by day, week or month
        if send_email_by == 'month':
            all_memories_photos = filter_photos_by_month(all_photos, month)
        elif send_email_by == 'week':
            all_memories_photos = filter_photos_by_week(all_photos, week)
        elif send_email_by == 'day':
            all_memories_photos = filter_photos_by_day(all_photos, day, month)
        else:
            logging.info(f"Invalid sendEmailBy setting: {send_email_by}! Assuming send_email_by=day")
            all_memories_photos = filter_photos_by_day(all_photos, day, month)
            
        last_memories_build_date = date

    if send_email == "Y":
        random_memories_photos = get_random_memories_photos(all_memories_photos, send_email_max_photos)
        send_result_email(sid, random_memories_photos, send_email_service, send_email_service_port, send_email_from, send_email_to, send_email_subject, send_email_password)
    
    logout()
    
def rebuild_photos_cache_build_memories_and_send_email(send_email = "Y", date = None, wait = False):
    logging.info("Rebuilding photos cache ()... ")
    
    sid = login()
    
    # Since
    global last_memories_build_date, full_refresh_required
    last_memories_build_date = None
    
    # If is time to do a full refresh...
    if full_refresh_required:
        logging.info("Its time to do a full refresh! Cleaning all cache objects!")
        
        global all_folders, all_photos, all_photos_with_gps, all_memories_photos
        all_folders, all_photos, all_photos_with_gps, all_memories_photos = {}, {}, {}, {}
        
        full_refresh_required = False
    
    # Start the fetching thread
    fetch_all_photos_thread = threading.Thread(target=fetch_all_photos, args=(sid, ))
    fetch_all_photos_thread.start()

    # Start the wait-and-send_email thread if requested
    email_thread = threading.Thread(target=build_memories_and_send_email, args=(sid, date, send_email, fetch_all_photos_thread, ))
    email_thread.start()

    if wait:
        email_thread.join()
    
# Getting photos during zoom abandoned. It gave too many errors while navigating thru the photos because browsing thru them triggers zooming and unwanted recalculations
# Define a route to return the photos that are inside a lat/long square
#@app.route("/api/photos", methods=["GET"])
#def get_photos():
#    logging.info("Routing %s/%s (%d, %d, %d)", request.path, request.args, len(all_photos), len(all_photos_with_gps), len(all_memories_photos))
#
#    # Get bounds from the request
#    min_lat = float(request.args.get("minLat"))
#    max_lat = float(request.args.get("maxLat"))
#    min_lng = float(request.args.get("minLng"))
#    max_lng = float(request.args.get("maxLng"))
#
#    # Filter photos within bounds
#    visible_photos = {
#        photo_id : photo for photo_id, photo in all_photos_with_gps.items() if min_lat <= photo["photo_data"]["original"]["additional"]["gps"]["latitude"] <= max_lat and min_lng <= photo["photo_data"]["original"]["additional"]["gps"]["longitude"] <= max_lng
#    }
#
#    logging.info("Routed %s/%s (returning %d photos)", request.path, request.args, len(visible_photos))
#
#    return jsonify(visible_photos)

# Not needed nor used!
## Define a custom filters
#def phyton_format_datetime(value, format='%d/%m/%Y'):
#    return datetime.fromtimestamp(value).strftime(format)

def get_number_of_photos_and_videos(photos):
    num_photos = num_videos = 0
    for photo in photos.values():
        if photo['photo_data']['original']['type'] == "photo":
            num_photos += 1
        elif photo['photo_data']['original']['type'] == "video":
            num_videos += 1
    return num_photos, num_videos

def render_response(route, context):
    logging.info("Routing %s (%d, %d, %d): %s", route, len(all_photos), len(all_photos_with_gps), len(all_memories_photos), request.args)

    if context == MEMORIES_CONTEXT:
        template = "memories.html"
        photos_to_consider = all_memories_photos
    else: # MAP_CONTEXT or anything else...
        template = "map.html"
        photos_to_consider = all_photos_with_gps

    num_photos, num_videos = get_number_of_photos_and_videos(photos_to_consider)
            
    # Getting photos during zoom abandoned. It gave too many errors while navigating thru the photos because browsing thru them triggers zooming and unwanted recalculations
    #if (visibleThreshold == 0 or (photos_to_consider and len(photos_to_consider) < visibleThreshold)):
    #    logging.info("Number of photos (%d) is less then %d. Photos will not be refreshed during zoom, all photos added!", len(photos_to_consider), visibleThreshold)

    # Not needed nor used!
    # Create and configure the environment
    #template_env = Environment(loader=FileSystemLoader('templates'))
    #template_env.filters['phyton_format_datetime'] = phyton_format_datetime
    # Now render the template using this environment 
    #template = template_env.get_template('memories.html')
    #return template.render(photos=all_memories_photos, numPhotos=num_photos, numVideos=num_videos)

    return render_template(template, photos = photos_to_consider, numPhotos=num_photos, numVideos=num_videos)

    #else:
    #    logging.info("Number of photos (%d) is 0 or greater then %d. Photos will be refreshed during zoom!", len(photos_to_consider), visibleThreshold)
    #    return render_template("map.html", photos = None)

@app.route("/", methods=["GET"])
@app.route("/map", methods=["GET"])
def render_photos_map():
    return render_response(request.path, MAP_CONTEXT)

# Sample: https://<this container host and port>/memories?date=1027&send_email=Y
@app.route("/memories", methods=["GET"])
def render_memories():
    logging.info("Routing %s/%s (%d, %d, %d)", request.path, request.args, len(all_photos), len(all_photos_with_gps), len(all_memories_photos))

    # Get the optional date string in the format 'MMDD' (default to None if not provided)
    date_str = request.args.get('date', None)
    
    # Check if the date_str is provided and if it matches the correct format 'MMDD'
    date = None
    if date_str and len(date_str) == 4 and date_str.isdigit():
        try:
            date = datetime.strptime(str(datetime.now().year) + date_str, '%Y%m%d')
        except ValueError:
            logging.info("Error routing %s/%s (%d, %d, %d): Invalid date received (MMDD)", request.path, request.args, len(all_photos), len(all_photos_with_gps), len(all_memories_photos))
            

    # Get the optional 'Y'/'N' parameter (default to None if not provided)
    send_email = request.args.get('send_email', 'N')

    sid = login()

    build_memories_and_send_email(sid, date, send_email)
    
    logging.info("Routed %s/%s (Rebuilding photos cache thread started!)", request.path, request.args)

    context = request.args.get("context")

    return render_response(request.path, MEMORIES_CONTEXT)
        
# Sample: https://<this container host and port>/rebuild?date=1027&context=Memories&send_email=Y
@app.route("/rebuild")
def rebuild_cache():
    logging.info("Routing %s/%s (%d, %d, %d)", request.path, request.args, len(all_photos), len(all_photos_with_gps), len(all_memories_photos))
    
    # Get the optional date string in the format 'MMDD' (default to None if not provided)
    date_str = request.args.get('date', None)
    
    # Check if the date_str is provided and if it matches the correct format 'MMDD'
    date = None
    if date_str and len(date_str) == 4 and date_str.isdigit():
        try:
            date = datetime.strptime(str(datetime.now().year) + date_str, '%Y%m%d')
        except ValueError:
            logging.info("Error routing %s/%s (%d, %d, %d): Invalid date received (MMDD)", request.path, request.args, len(all_photos), len(all_photos_with_gps), len(all_memories_photos))

    # Get the optional 'Y'/'N' parameter (default to None if not provided)
    send_email = request.args.get('send_email', 'N')
    
    # Get the context
    context = request.args.get("context", MAP_CONTEXT)

    rebuild_photos_cache_build_memories_and_send_email(send_email, date, True)
    
    logging.info("Routed %s/%s (Rebuilding photos cache thread started!)", request.path, request.args)

    context = request.args.get("context")
    
    return render_response(request.path, context)

def set_full_refresh_flag():
    global full_refresh_required

    full_refresh_required = True

# Schedule the photo refresh every night at 1:30 AM
def schedule_refreshs():
    scheduler = BackgroundScheduler(defaults={'misfire_grace_time': 300})
    scheduler.start()

    # Schedule soft refresh and memories mail
    scheduler.add_job(rebuild_photos_cache_build_memories_and_send_email, 'cron', hour=rebuildHour, minute=0, misfire_grace_time=900)
    logging.info("Scheduler started. Photos will soft refresh at %d:00 AM daily.", rebuildHour)

    # Schedule hard refresh
    scheduler.add_job(set_full_refresh_flag, 'cron', day_of_week='sun', hour=rebuildHour - 1, minute=0, misfire_grace_time=900)
    logging.info("Scheduler started. Photos will hard refresh sundays %d:00 AM weekly.", rebuildHour - 1)

    # List all scheduled jobs
    #jobs = scheduler.get_jobs()
    #for job in jobs:
    #    logging.info(f"Scheduled Job: {job.id}, Next Run Time: {job.next_run_time}")

# TODO: Debug only
#def set_avi_timestamps():
#    sid = login()
#
#    offset = 0
#    limit = 2500  # Set a reasonable limit for each request
#    while True:
#        response = call_api("entry", {"api": f"SYNO.{fotoSpace}.Browse.Item", "version": 6, "method": "list", "_sid": sid, "offset": offset, "limit": limit})
#
#        if response.status_code == 200:
#            data = response.json()
#            if data["success"]:
#                photos = data["data"]["list"]
#
#                for photo in photos:
#                    id_val=photo["id"]
#                    photo_name = photo['filename']
#                    if photo['type'] == "video" and get_mime_type(photo_name) == "video/avi":
#                        folder_name = get_folder_name(sid, photo["folder_id"])
#                        epoch_time = 0
#                        try:
#                            date_time_str = photo_name[:19]
#                            dt = datetime.strptime(date_time_str, "%Y-%m-%d_%H-%M.%S")
#                            epoch_time = int(time.mktime(dt.timetuple()))
#                        except Exception as e:
#                            try:
#                                date_time_str = folder_name[1:11]
#                                dt = datetime.strptime(date_time_str, "%Y-%m-%d")
#                                epoch_time = int(time.mktime(dt.timetuple()))
#                            except Exception as e:
#                                logging.error(f"Error getting avi date for {folder_name}/{photo_name}! {e}")
#                                continue
#
#                        response = call_api("entry", {"api": f"SYNO.{fotoSpace}.Browse.Item", "version": 2, "method": "set", "id": f"[{id_val}]", "time": epoch_time, "_sid": sid})
#                        data = response.json()
#                        if not data["success"]:
#                            logging.error(f"Error getting avi date for {folder_name}/{photo_name}! {data}")
#                            return f"Error getting avi date for {folder_name}/{photo_name}! {data}"
#                            
#                        logging.info(f"Setted date (folder) {epoch_time} date for {folder_name}/{photo_name}: {response.json()}")
#                        
#                if len(photos) < limit:
#                    break  # Exit the loop if we fetched the last page
#                offset += limit  # Increment offset for the next page
#            else:
#                raise Exception(f"Failed to list photos: {data}")
#        else:
#            raise Exception(f"Error fetching photos: {response}")
#
#    logging.info(f"AVI dates seted!")

if __name__ == "__main__":

    #get_api_info("SYNO.Foto.Browse.Folder")
    #get_api_info("SYNO.FotoTeam.Browse.Folder")
    #get_api_info("SYNO.Foto.Browse.Item")
    #get_api_info("SYNO.FotoTeam.Browse.Item")
    #get_api_info("SYNO.Foto.Download")
    #get_api_info("SYNO.FotoTeam.Download")
    #get_api_info("SYNO.Foto.Thumbnail")
    #get_api_info("SYNO.FotoTeam.Thumbnail")
    #get_api_info("SYNO.API.Auth")
    #get_api_info("SYNO.API.Info")
    #get_api_info("all")

    # TODO: Debug only
    # Setting avi files timestamps based on its file or folder name
    #set_avi_timestamps()

    rebuild_photos_cache_build_memories_and_send_email()
    

    schedule_refreshs()

    app.run(host="0.0.0.0", port=flaskPort)