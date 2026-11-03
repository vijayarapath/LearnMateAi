bind = "unix:/run/learnmate/gunicorn.sock"
workers = 3                # (2 x CPU cores) + 1
timeout = 90               # AI calls can take a while
accesslog = "-"
errorlog = "-"
