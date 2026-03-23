FROM metasploitframework/metasploit-framework:latest

ENV MSF_USER=msf \
    MSF_PASSWORD=msf \
    MSF_PORT=55553 \
    MSF_SSL=false

ENTRYPOINT ["bash", "-lc"]
CMD ["if [ \"$MSF_SSL\" = \"true\" ]; then exec /usr/src/metasploit-framework/msfrpcd -f -U \"$MSF_USER\" -P \"$MSF_PASSWORD\" -a 0.0.0.0 -p \"$MSF_PORT\"; else exec /usr/src/metasploit-framework/msfrpcd -f -S -U \"$MSF_USER\" -P \"$MSF_PASSWORD\" -a 0.0.0.0 -p \"$MSF_PORT\"; fi"]
