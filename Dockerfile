FROM alpine:3.21

WORKDIR /youtubebot
COPY . ./

RUN apk add --no-cache python3 py3-pip pipx ffmpeg

# Use RUN to install Python packages (numpy and scipy) via pip, Python's package manager
RUN pip install discord.py pynacl yt_dlp python-dotenv --break-system-packages


CMD ["python3", "./youtubebot.py"]