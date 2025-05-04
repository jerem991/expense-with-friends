#!/bin/bash

# --- Configuration ---
# Replace with your actual container name or ID
CONTAINER_NAME_OR_ID="your_postgres_container_name_or_id"
# Replace with the name of the database you want to dump/restore
DATABASE_NAME="your_database_name"
# Replace with the desired path on your Windows filesystem (using WSL path format)
# This directory will store your backup files.
# Example: /mnt/c/Users/YourUsername/PostgresBackups/
WINDOWS_BACKUP_DIR="/mnt/c/path/to/your/windows/backup/directory"
# Number of recent dumps to keep
NUM_DUMPS_TO_KEEP=10

# --- Optional: PostgreSQL User and Password ---
# It's recommended to set these as environment variables in your WSL session
# before running the script, or use a .pgpass file.
# export PGUSER="your_db_user"           # e.g., postgres
# export PGPASSWORD="your_db_password"   # !! Handle securely, don't hardcode in scripts

# --- Functions ---

# Function to perform a database dump
perform_dump() {
  echo "--- Performing Database Dump ---"

  # Check if the target Windows directory exists in WSL
  if [ ! -d "$WINDOWS_BACKUP_DIR" ]; then
    echo "Error: Target Windows backup directory not found in WSL: $WINDOWS_BACKUP_DIR"
    echo "Please ensure the directory exists and is accessible from WSL."
    exit 1
  fi

  # Define the name of the dump file with a timestamp
  DUMP_FILE_NAME="${DATABASE_NAME}_$(date +%Y%m%d_%H%M%S).sqlc" # Using .sqlc for custom format
  # Combine the target directory and file name
  NEW_DUMP_PATH="${WINDOWS_BACKUP_DIR}/${DUMP_FILE_NAME}"

  echo "Attempting to dump database '$DATABASE_NAME' from container '$CONTAINER_NAME_OR_ID'..."
  echo "Saving new dump to: $NEW_DUMP_PATH"

  # Execute pg_dump inside the container and direct output to the Windows path
  # We use docker exec to run the command inside the container.
  # The default user for postgres containers is often 'postgres',
  # so we switch user (-u postgres) to avoid potential permission issues inside the container.
  # We pass PGUSER and PGPASSWORD as environment variables to docker exec
  # so pg_dump can authenticate without needing a .pgpass file or prompting.
  # Using -Fc for custom format dump, suitable for pg_restore.
  docker exec -u postgres \
    -e PGDATABASE="$DATABASE_NAME" \
    ${PGUSER+-e PGUSER="$PGUSER"} \
    ${PGPASSWORD+-e PGPASSWORD="$PGPASSWORD"} \
    "$CONTAINER_NAME_OR_ID" \
    pg_dump -Fc \
    > "$NEW_DUMP_PATH"

  # Check the exit status of the docker exec command
  if [ $? -eq 0 ]; then
    echo "Database dump successful!"
    echo "New dump saved to $NEW_DUMP_PATH"

    # --- Size Check Logic ---
    NEW_DUMP_SIZE=$(stat -c%s "$NEW_DUMP_PATH" 2>/dev/null) # Get size in bytes, suppress errors if file not found immediately

    if [ -z "$NEW_DUMP_SIZE" ]; then
        echo "Warning: Could not determine the size of the new dump file."
    else
        echo "New dump size: ${NEW_DUMP_SIZE} bytes."

        # Find the most recent previous dump file (excluding the one just created)
        PREVIOUS_DUMP_PATH=$(ls -t "$WINDOWS_BACKUP_DIR"/${DATABASE_NAME}_*.sqlc 2>/dev/null | grep -v "$(basename "$NEW_DUMP_PATH")" | head -n 1)

        if [ -n "$PREVIOUS_DUMP_PATH" ]; then
            PREVIOUS_DUMP_SIZE=$(stat -c%s "$PREVIOUS_DUMP_PATH" 2>/dev/null)
            if [ -n "$PREVIOUS_DUMP_SIZE" ]; then
                echo "Most recent previous dump: $(basename "$PREVIOUS_DUMP_PATH") (${PREVIOUS_DUMP_SIZE} bytes)"

                # Compare sizes
                if [ "$NEW_DUMP_SIZE" -lt "$PREVIOUS_DUMP_SIZE" ]; then
                    echo "----------------------------------------------------------------------"
                    echo "WARNING: The new dump (${NEW_DUMP_SIZE} bytes) is smaller than the most recent previous dump (${PREVIOUS_DUMP_SIZE} bytes)."
                    echo "This might indicate an issue with the dump process or data loss."
                    echo "Please investigate!"
                    echo "----------------------------------------------------------------------"
                else
                    echo "New dump size is not smaller than the previous one. Size check passed."
                fi
            else
                echo "Warning: Could not determine the size of the most recent previous dump file."
            fi
        else
            echo "No previous dumps found for size comparison."
        fi
    fi

    # --- Backup Retention Logic (Keep last NUM_DUMPS_TO_KEEP) ---
    echo "Checking backup retention policy (keeping last $NUM_DUMPS_TO_KEEP dumps)..."
    # List all dumps, sort by time (newest first), skip the ones to keep, and list the rest
    OLD_DUMPS=$(ls -t "$WINDOWS_BACKUP_DIR"/${DATABASE_NAME}_*.sqlc 2>/dev/null | tail -n +$((NUM_DUMPS_TO_KEEP + 1)))

    if [ -n "$OLD_DUMPS" ]; then
      echo "Removing old dumps:"
      echo "$OLD_DUMPS" | while read old_dump; do
        echo "Deleting: $old_dump"
        rm "$old_dump"
      done
    else
      echo "No old dumps found to remove."
    fi

  else
    echo "Error: Database dump failed."
    # You might want to check the container logs for more details:
    # docker logs "$CONTAINER_NAME_OR_ID"
    exit 1
  fi
}

# Function to restore a database dump
perform_restore() {
  echo "--- Performing Database Restore ---"

  if [ -z "$1" ]; then
    echo "Error: No dump file path provided for restore."
    echo "Usage: $0 restore /mnt/c/path/to/your/windows/backup/directory/your_dump_file.sqlc"
    exit 1
  fi

  DUMP_FILE_TO_RESTORE="$1"

  # Check if the dump file exists
  if [ ! -f "$DUMP_FILE_TO_RESTORE" ]; then
    echo "Error: Dump file not found: $DUMP_FILE_TO_RESTORE"
    exit 1
  fi

  echo "Attempting to restore database '$DATABASE_NAME' from dump file:"
  echo "$DUMP_FILE_TO_RESTORE"
  echo ""
  echo "----------------------------------------------------------------------"
  echo "WARNING: Restoring will DROP and recreate the database '$DATABASE_NAME'."
  echo "All existing data in this database will be LOST."
  echo "----------------------------------------------------------------------"
  echo "Are you sure you want to continue? (yes/no)"
  read confirmation

  if [[ "$confirmation" != "yes" ]]; then
    echo "Restore cancelled by user."
    exit 0
  fi

  echo "Starting restore process..."

  # Use docker exec -i to pipe the dump file into pg_restore inside the container
  # --clean: drops database objects before recreating them
  # --if-exists: adds IF EXISTS to drop commands
  cat "$DUMP_FILE_TO_RESTORE" | docker exec -i -u postgres \
    -e PGDATABASE="$DATABASE_NAME" \
    ${PGUSER+-e PGUSER="$PGUSER"} \
    ${PGPASSWORD+-e PGPASSWORD="$PGPASSWORD"} \
    "$CONTAINER_NAME_OR_ID" \
    pg_restore --clean --if-exists -d "$DATABASE_NAME"

  # Check the exit status of the docker exec command
  if [ $? -eq 0 ]; then
    echo "Database restore successful!"
  else
    echo "Error: Database restore failed."
    # Check container logs for more details if needed
    # docker logs "$CONTAINER_NAME_OR_ID"
    exit 1
  fi
}

# --- Main Script Logic ---

# Check if a command (dump or restore) is provided
if [ -z "$1" ]; then
  echo "Usage: $0 <command> [options]"
  echo "Commands:"
  echo "  dump      Perform a database dump."
  echo "  restore   Restore a database from a dump file."
  echo ""
  echo "For restore:"
  echo "  $0 restore /mnt/c/path/to/your/windows/backup/directory/your_dump_file.sqlc"
  exit 1
fi

COMMAND="$1"
shift # Remove the first argument (the command)

case "$COMMAND" in
  dump)
    perform_dump
    ;;
  restore)
    perform_restore "$@" # Pass remaining arguments to the restore function
    ;;
  *)
    echo "Error: Invalid command '$COMMAND'."
    echo "Usage: $0 <command> [options]"
    echo "Commands:"
    echo "  dump      Perform a database dump."
    echo "  restore   Restore a database from a dump file."
    exit 1
    ;;
esac


