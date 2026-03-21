# AV/EDR Bypass Techniques

## API Unhooking
- EDRs hook ntdll/kernel32 functions by inserting JMP to inspection module
- Bypass: read clean ntdll.dll from disk, overwrite hooked .text section in memory
- Restores original syscall stubs, bypassing inline hooks
- Common hooked APIs: CreateRemoteThread, NtQueueApcThread, MiniDumpWriteDump

## Direct Syscalls
- Skip hooked API layer entirely by invoking syscalls directly
- Write ASM stubs with correct syscall numbers (OS-version specific)
```asm
SysNtCreateFile proc
    mov r10, rcx
    mov eax, 55h    ; NtCreateFile syscall number (Win10)
    syscall
    ret
SysNtCreateFile endp
```
- Reference: j00ru.vexillium.org/syscalls/nt/64/

## ACG (Arbitrary Code Guard) Bypass
- Use `SetProcessMitigationPolicy` to prevent dynamic code generation
- Bypass via ROP chains or JIT-based techniques

## AV Template Bypass
- Metasploit: use custom templates to change binary signature
- Modify 1-2 bytes in shellcode launcher to break static signatures

## Software Packing (T1045)
```cmd
upx.exe -9 -o packed.exe original.exe
```
- Reduces file size ~50%, changes PE section headers
- Detection: UPX0/UPX1 section names, Raw Size=0 with large Virtual Size
- Low import count indicates packed binary

## DotNetToJScript
- Execute C# assemblies from JScript/WScript without touching disk
- Useful for running payloads in script host processes
