# CSI Lab 1

Dependency-free Python implementation for the RS-232 and MODBUS-ASCII lab.

## Quick commands

This workspace uses the bundled Codex Python runtime. If plain `python` only prints
`Python` on Windows, run the commands through the `.bat` scripts in `scripts/`.

List detected COM ports:

```powershell
.\scripts\list_ports.bat
```

Verify a null-modem link between COM5 and COM6:

```powershell
.\scripts\smoke_test_com5_com6.bat
```

Run Task 1 terminal in two separate terminals:

```powershell
.\scripts\task1_com5.bat
.\scripts\task1_com6.bat
```

Run Task 2 MODBUS-ASCII master/slave in two separate terminals:

```powershell
.\scripts\task2_slave_com6.bat
.\scripts\task2_master_com5.bat
```

Inside the master:

```text
/write 1 Hello slave
/read 1
/broadcast Hello everyone
```
