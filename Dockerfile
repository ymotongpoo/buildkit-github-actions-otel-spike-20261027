FROM busybox:1.37.0
WORKDIR /app
COPY message.txt .
RUN cat message.txt > result.txt
CMD ["cat", "/app/result.txt"]
