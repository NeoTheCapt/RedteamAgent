# nmap

**Purpose:** Port/service discovery and enumeration
For live engagement targets, run Nmap through the engagement container with `run_tool nmap`.

**Quick:** `run_tool nmap -sV -sC -T4 target`
**Full:** `run_tool nmap -sV -sC -T4 -p- target`
**UDP:** `run_tool nmap -sU --top-ports 50 target`
**Specific ports:** `run_tool nmap -sV -sC -p 80,443,8080 target`
**OS detection:** `run_tool nmap -O -sV target`
**Output:** `-oN file.txt` (normal), `-oX file.xml` (XML), `-oA basename` (all formats)
