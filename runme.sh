#!/usr/bin/env bash

# Supervisor script to start/stop/status three project processes:
# - extraction.py
# - scripts/save-game-cleanup.py
# - show-data.py (streamlit)
#
# Usage: ./runme.sh start|stop|restart|status [name]
# where [name] is one of: extraction, cleanup, streamlit

set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_DIR="$BASE_DIR/runme.pids"
LOG_DIR="$BASE_DIR/runme.logs"
mkdir -p "$PID_DIR" "$LOG_DIR"

# Use venv python if available
VENV_PY="$BASE_DIR/.venv/bin/python"
if [[ -x "$VENV_PY" ]]; then
	PYTHON="$VENV_PY"
else
	PYTHON="python"
fi

declare -A CMD
declare -A PIDFILE
declare -A LOGFILE

CMD[extraction]="$PYTHON $BASE_DIR/extraction.py"
CMD[cleanup]="$PYTHON $BASE_DIR/scripts/cleanup_saves.py"
CMD[streamlit]="$PYTHON -m streamlit run $BASE_DIR/show-data.py"

PIDFILE[extraction]="$PID_DIR/extraction.pid"
PIDFILE[cleanup]="$PID_DIR/cleanup.pid"
PIDFILE[streamlit]="$PID_DIR/streamlit.pid"

LOGFILE[extraction]="$LOG_DIR/extraction.log"
LOGFILE[cleanup]="$LOG_DIR/cleanup.log"
LOGFILE[streamlit]="$LOG_DIR/streamlit.log"

is_running() {
	local pidfile="$1"
	if [[ -f "$pidfile" ]]; then
		local pid
		pid=$(<"$pidfile")
		if kill -0 "$pid" 2>/dev/null; then
			echo "$pid"
			return 0
		else
			return 1
		fi
	fi
	return 1
}

start_one() {
	local name=$1
	local cmd=${CMD[$name]}
	local pidfile=${PIDFILE[$name]}
	local logfile=${LOGFILE[$name]}

	if pid=$(is_running "$pidfile"); then
		echo "$name already running (pid $pid)"
		return 0
	fi

	echo "Starting $name..."
	nohup bash -lc "$cmd" >"$logfile" 2>&1 &
	echo $! > "$pidfile"
	sleep 0.1
	pid=$(<"$pidfile")
	echo "$name started (pid $pid) - log: $logfile"
}

stop_one() {
	local name=$1
	local pidfile=${PIDFILE[$name]}

	if pid=$(is_running "$pidfile"); then
		echo "Stopping $name (pid $pid)..."
		kill "$pid" || true
		# wait up to 5 seconds
		for i in {1..10}; do
			if ! kill -0 "$pid" 2>/dev/null; then
				break
			fi
			sleep 0.5
		done
		if kill -0 "$pid" 2>/dev/null; then
			echo "Force killing $pid"
			kill -9 "$pid" || true
		fi
		rm -f "$pidfile"
		echo "$name stopped"
	else
		echo "$name not running"
	fi
}

status_one() {
	local name=$1
	local pidfile=${PIDFILE[$name]}
	if pid=$(is_running "$pidfile"); then
		echo "$name running (pid $pid)"
	else
		echo "$name stopped"
	fi
}

start_all() {
	for n in "extraction" "cleanup" "streamlit"; do
		start_one "$n"
	done
}

stop_all() {
	for n in "streamlit" "cleanup" "extraction"; do
		stop_one "$n"
	done
}

status_all() {
	for n in "extraction" "cleanup" "streamlit"; do
		status_one "$n"
	done
}

usage() {
	cat <<EOF
Usage: $0 <command> [name]
Commands:
	start [name]    Start a process or all if name omitted
	stop [name]     Stop a process or all if name omitted
	restart [name]  Restart a process or all if name omitted
	status [name]   Show status of a process or all if name omitted
	logs [name]     Tail the log for a process (requires name)
Names: extraction, cleanup, streamlit
EOF
}

case ${1:-} in
	start)
		if [[ -n ${2:-} ]]; then
			start_one "$2"
		else
			start_all
		fi
		;;
	stop)
		if [[ -n ${2:-} ]]; then
			stop_one "$2"
		else
			stop_all
		fi
		;;
	restart)
		if [[ -n ${2:-} ]]; then
			stop_one "$2"
			start_one "$2"
		else
			stop_all
			start_all
		fi
		;;
	status)
		if [[ -n ${2:-} ]]; then
			status_one "$2"
		else
			status_all
		fi
		;;
	logs)
		if [[ -n ${2:-} ]]; then
			tail -f "${LOGFILE[$2]}"
		else
			echo "Please provide a name to tail logs for"
			usage
			exit 2
		fi
		;;
	*)
		usage
		exit 2
		;;
esac
