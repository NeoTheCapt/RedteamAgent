# nmap

**Purpose:** Port/service discovery and enumeration

**Quick:** `nmap -sV -sC -T4 target`
**Full:** `nmap -sV -sC -T4 -p- target`
**UDP:** `nmap -sU --top-ports 50 target`
**Specific ports:** `nmap -sV -sC -p 80,443,8080 target`
**OS detection:** `nmap -O -sV target`
**Output:** `-oN file.txt` (normal), `-oX file.xml` (XML), `-oA basename` (all formats)
