

# Synology Memories And Geo Mapping

Like must of you, I used google photos since it was born but after I ran out of storage space and switched to Synology, I missed my “memories” features…
It all started with [treygordon/synology-photos-memories](https://hub.docker.com/r/treygordon/synology-photos-memories) and the strategy was to create a Docker project and use it as the base for all the features I’m now sharing.
That said, this container project scans photos and videos on your Synology and sends a mail with your memories. It also allows you to share, see, play, browse and check their geographic locations (even for mp4 files since i'm using ffmpeg to be able to extract the exif available metadata).
The first execution, if you have, like me, more then 60.000 photos and videos, can take some time. (mine typically takes 15 to 20 minutes and this is due to the fact that I'm using ffmpeg to check for the geo-location of every MP4 files - unfortunately Synology doesn't natively support this feature). After that we only look for changes daily at a specified hour (<REBUILD_HOUR>) and on Sundays (also at <REBUILD_HOUR> hour) we do again a full refresh,

### Screenshots
![Map Sample](https://github.com/PedroAragaoDias/synology-photos-memories-and-geo-mapping/blob/main/instructions/Map%201.png?raw=true)
![Map Sample](https://github.com/PedroAragaoDias/synology-photos-memories-and-geo-mapping/blob/main/instructions/Map%202.png?raw=true)
![Map Sample](https://github.com/PedroAragaoDias/synology-photos-memories-and-geo-mapping/blob/main/instructions/Map%203.png?raw=true)
![Map Sample](https://github.com/PedroAragaoDias/synology-photos-memories-and-geo-mapping/blob/main/instructions/Map%204.png?raw=true)
![Map Sample](https://github.com/PedroAragaoDias/synology-photos-memories-and-geo-mapping/blob/main/instructions/Memories%20Page.png?raw=true)

> I have only tested this container in DSM 7.2
> 
> You need to download and install synology package "Docker Manager"

In order to install this project, after downloading the Docker Manager, you have to go to it's "Registry" tab, search for "pedroaragaodias/synology-photos-memories-and-geo-mapping" and download the latest version.

![Download Image](https://github.com/PedroAragaoDias/synology-photos-memories-and-geo-mapping/blob/main/instructions/Download%20Image.png?raw=true)

### General Concepts
>**<synology_dsm_local_host>** <=> ***"Server name:"***
> 
> ![Synology host](https://github.com/PedroAragaoDias/synology-photos-memories-and-geo-mapping/blob/main/instructions/Synology%20Host%20Name.png?raw=true)

>**<synology_dsm_port>** <=> ***"DSM port (HTTPS):"***
> 
> ![DSM Port](https://github.com/PedroAragaoDias/synology-photos-memories-and-geo-mapping/blob/main/instructions/Synology%20DSM%20Port.png?raw=true)

>**<synology_ddns_name>** <=> ***"Hostname:"***
> 
> ![Synology DDNS](https://github.com/PedroAragaoDias/synology-photos-memories-and-geo-mapping/blob/main/instructions/Synology%20DDNS.png?raw=true)

After installing "Docker Manager", you just need to go to the "Image" tab, select "Run", configure the container port settings and change the environment variables according to you synology installation.
In the "Run" window "General Settings" chose a name for your container (e.g. *photos-memories*) and click "Next". Then, in the "Advanded Settings" window, chose a "Local Port" (this can by any available port e.g. *12345*) and, for the "Container Port", select the same value that is defined for the FLASK_PORT environment variable (you can chose any available port but by default, as you can check bellow, i've chosen 5000).
After defining the container ports, adjust the environment variables bellow:

![Port Settings e Environment Variables](https://github.com/PedroAragaoDias/synology-photos-memories-and-geo-mapping/blob/main/instructions/Port%20Settings%20&%20Environment%20variables.png?raw=true)

| Variable Name                                                                     | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
|-----------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| FLASK_PORT=5000                                                                   | Flask listen port. This value has to be the same that the "Container Port"                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| NAS_USER_ID=<synology_username>                                                   | Your user name in synology                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| NAS_USER_PASSWORD=<synology_username_password>                                    | The corresponding credentials                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| NAS_INTERNAL_PHOTO_HOST=https://<synology_dsm_local_host>:<synology_dsm_port>     | The local host name and port for the synology Photos API (<synology_dsm_local_host> is defined in "Control Panel" > "Network" > "Server Name" and <synology_dsm_port> is defined in "Login Portal" > "DSM port (HTTPS)")                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| NAS_EXTERNAL_PHOTO_HOST=https://<synology_ddns_name>:<synology_dsm_port>          | The external host name and port for the synology Photos API. This is the base link to access the photos and videos - I have created a new entry in the "Login Portal" > "Reverse Proxy" that maps dsm.<synology_ddns_name>:443 to Photos API host localhost:<synology_ddns_port>. Note that you have to configure <synology_ddns_name> in "External Access" > "DDNS". If you prefer to create the reverse proxy like me, you can use something like NAS_EXTERNAL_CONTAINER_HOST = https://dsm.<synology_ddns_name> as stated above. The <synology_ddns_name> and <synology_dsm_port> are defined in "Control Panel" > "Network" > "Server name" and "Control Panel" > "Login Portal" > "DSM port (HTTPS)" |
| NAS_EXTERNAL_CONTAINER_HOST=https://<synology_ddns_name>:<container_local_port>   | The external host name where the docker container is installed and how you access the pages - Also here i have created a new entry in the "Login Portal" > "Reverse Proxy" that maps photos.<synology_ddns_name>:443 to my docker container host localhost:<container_local_port> (see section "Port Settings"). If you prefer to create the reverse proxy like me, you can use something like NAS_EXTERNAL_CONTAINER_HOST=https://photos.<synology_ddns_name> as stated above. The <container_local_port> is user defined when running the container. You can choose any available port                                                                                                                  |
| REBUILD_HOUR=6                                                                    | Daily, at this hour, the photos cache will be refreshed                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| FOTO_TEAM=true                                                                    | If ommited or true the shared photo space will be considered, if false the personal photo space will be considered                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| SEND_EMAIL_SERVICE=smtp.gmail.com                                                 | gmail server from where the memories photos are sent                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| SEND_EMAIL_SERVICE_PORT=587                                                       | gmail server port from where the memories photos are sent                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| SEND_EMAIL_BY=day                                                                 | Periodicity of the mail (day, week or month)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| SEND_EMAIL_FROM=<gmail_sender_account>                                            | gmail sender account                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| SEND_EMAIL_PASSWORD=<gmail_app_password>                                          | gmail APP password. To enable gmail APP passwords on the SEND_EMAIL_FROM account go to https://myaccount.google.com/security -> Turn 2-step verification ON and go to https://myaccount.google.com/apppasswords                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| SEND_EMAIL_TO=<mail_address1, mailaddress2, ...>                                  | Destination mail addresses comma separated                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| SEND_EMAIL_HOUR=6                                                                 | Hour the mail will be sent                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| SEND_EMAIL_SUBJECT="Family Memories"                                              | Mail subject                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| SEND_EMAIL_MAX_PHOTOS=0                                                           | Maximum number of photos to include in the mail message (0 means all. If any other value, they will be selected randomly)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| SEND_EMAIL_PHOTO_MOZAIC_ROW_MAX_WIDTH=1350                                        | Maximum with of each mail line with photos (best value for 1920 x 1080)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| SEND_EMAIL_PHOTO_MOZAIC_HEIGHT=220                                                | Height of the mail photos sent                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| EXCLUDE_FOLDERS_IDS="[ FolderId_1, FolderId_2, ... ]"                             | If you want to exclude some folders there are 2 ways. Giving the folder_id (EXCLUDE_FOLDERS_IDS) and or its name (EXCLUDE_FOLDERS_NAMES). Both can be used simultaneously.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| EXCLUDE_FOLDERS_NAMES="[ \"/Folder Name 1\", \"/Folder Name 2/Folder Child 1\" ]" | If you want to exclude some folders there are 2 ways. Giving the folder_id (EXCLUDE_FOLDERS_IDS) and or its name (EXCLUDE_FOLDERS_NAMES). Both can be used simultaneously. Note that the fist "/" seems to be always present                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |

### External Access
If, as me you want to be able to access this container from the internet, you must configure your router to allow connections to this container. To archive that, go to "Control Panel" > "External Access", select the "Router Configuration" tab, "Create" a "Built-in application" and select your container from the list.

![External Access](https://github.com/PedroAragaoDias/synology-photos-memories-and-geo-mapping/blob/main/instructions/External%20Access.png?raw=true)

### Reverse Proxy
![Reverse Proxy](https://github.com/PedroAragaoDias/synology-photos-memories-and-geo-mapping/blob/main/instructions/Reverse%20Proxy.png?raw=true)

Here you can define the reverse proxies i've mentioned in the environment variables NAS_EXTERNAL_PHOTO_HOST and NAS_EXTERNAL_CONTAINER_HOST. 
e.g.  **DSM**: Reverse Proxy Name = DSM, Source Hostname = dsm.*your-ddns-name.myds.me*, Destination Port = 2222 (*Defined in "Login Portal" > "DSM port (HTTPS)"*) and **Photos**: Reverse Proxy Name = Photos, Source Hostname = photos.*your-ddns-name.myds.me*, Destination Port = 12345 (*The "Local Port" you choose when you started the container* <container_local_port>)

### Accessing the Container pages
- From the Intranet:
  - Photos Map: [http://<synology_dsm_local_host>:<container_local_port>/](http://<synology_dsm_local_host>:<container_local_port>/)
  - Memories: [http://<synology_dsm_local_host>:<container_local_port>/memories](http://<synology_dsm_local_host>:<container_local_port>/memories)
  
- From the Internet:
	- Not using Reverse Proxy: 
		 - Photos Map: [http://<synology_ddns_name>:<container_local_port>](http://<synology_ddns_name>:<container_local_port>)
		 - Memories: [https://<synology_ddns_name>:<container_local_port>/memories](https://%3Csynology_ddns_name%3E:%3Ccontainer_local_port%3E/memories)
  - Using Reverse Proxy
	  - Photos Map: [http://photos.<synology_ddns_name>](http://photos.<synology_ddns_name>)
	  - Memories: [http://photos.<synology_ddns_name>/memories](http://photos.<synology_ddns_name>/memories)

- ##### For the Memories page there are two parameters you can use:
	- date=MMDD - Defaults to current day
 	- send_email=Y or N - Defaults to N
	   >[http://photos.<synology_ddns_name>/memories?date=0131&send_mail=Y](http://photos.%3Csynology_ddns_name%3E/memories?date=0131&send_mail=Y)
	   >
       >[http://<synology_ddns_name><container_local_port>/memories?date=1231&send_mail=Y](http://%3Csynology_ddns_name%3E%3Ccontainer_local_port%3E/memories?date=1231&send_mail=Y)
       >
       >[http://<synology_dsm_local_host>:<container_local_port>/memories?date=0131&send_mail=N](http://<synology_dsm_local_host>:<container_local_port>/memories?date=0131&send_mail=N)

### Logs
If you need to check for any kind of problem logs are located here:
![Reverse Proxy](https://github.com/PedroAragaoDias/synology-photos-memories-and-geo-mapping/blob/main/instructions/Container%20Logs.png?raw=true)

### Github & DockerHub
github: [pedroaragaodias/synology-photos-memories-and-geo-mapping](https://github.com/pedroaragaodias/synology-photos-memories-and-geo-mapping)

dockerhub: [pedroaragaodias/synology-photos-memories-and-geo-mapping](https://hub.docker.com/repository/docker/pedroaragaodias/synology-photos-memories-and-geo-mapping)
### If you like to contribute, I’ve a paypal account https://paypal.me/pedroaragaodias ;-)
### Enjoy!!