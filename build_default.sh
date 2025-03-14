#!/bin/bash

# Get the directory of the script
SCRIPT_DIR=$(dirname "$0")

# Define the log file in the same directory as the script
LOG_FILE="$SCRIPT_DIR/build_and_start_logs.txt"

# Use a block to group multiple commands and redirect their output
{
	echo "###############################################################################################################################"

	echo `date` - Building synology-photos-memories-and-geo-mapping...
	docker --debug --log-level debug build -f $SCRIPT_DIR/Dockerfile_Default -t synology-photos-memories-and-geo-mapping:0.1 $SCRIPT_DIR
	# If we don't want to use cached files, and use debug...
	#   --debug --log-level debug ...build... --no-cache
	if [ $? -ne 0 ]; then
		echo `date` - synology-photos-memories-and-geo-mapping Build Failed!
	else
		echo `date` - synology-photos-memories-and-geo-mapping Built!

		#### Remove unused images
		#echo `date` - Purging unused images...
		#docker image prune -f
		#echo `date` - Unused images purged!
	fi

	echo "###############################################################################################################################"
} 2>&1 | tee $LOG_FILE

# Print a message indicating where the logs are saved
echo "Logs are saved in $LOG_FILE."