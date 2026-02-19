from bombshell import Process

url = "https://youtu.be/dQw4w9WgXcQ"
dest = "/tmp/never-gonna-give-you-up.%(ext)s"

Process("yt-dlp", url, "-o", dest).exec(with_spinner=True)
