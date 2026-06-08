# CSI Lab 1

Python implementation for CSI Laboratory Exercise 1: RS-232 communication control
and MODBUS-ASCII device communication.

The project is designed for one Windows PC with two USB-to-RS232 adapters and one
null-modem cable. It uses only the Python standard library and the Windows serial
API, so no external packages are required.

## Hardware Setup

Connect the devices as follows:

```text
Lab1_COM5 window -> COM5 -> USB-RS232 adapter #1
                                  |
                             null-modem cable
                                  |
Lab1_COM6 window -> COM6 -> USB-RS232 adapter #2
```

Only one program can open a COM port at a time. Close other serial terminals before
running these scripts.

## Recommended GUI

Open two PowerShell windows from the project directory and run:

```powershell
.\scripts\Lab1_COM5.bat
.\scripts\Lab1_COM6.bat
```

Press `Open COM` in both windows. The unified GUI has two tabs:

- `Task 1 - COM terminal`
- `Task 2 - MODBUS ASCII`

The unified GUI defaults to `9600 7E1`. This works for Task 1 ASCII text/PING and
matches the recommended MODBUS-ASCII character format for Task 2.

The `.bat` launchers use the bundled Python runtime path, which avoids the Windows
Store `python` alias issue on machines where plain `python` only prints `Python`.

## Task 1: RS-232 COM Terminal

Implemented obligatory features:

- COM port selection and detection.
- Transmission parameter configuration:
  - baud rate,
  - 7 or 8 data bits,
  - parity `N`, `E`, or `O`,
  - 1 or 2 stop bits.
- Data flow control selection:
  - none,
  - DTR/DSR,
  - RTS/CTS,
  - XON/XOFF.
- Terminator selection:
  - none,
  - CR,
  - LF,
  - CRLF,
  - custom 1- or 2-byte terminator.
- Text transmission and reception.
- Hex preview for transmitted and received bytes.
- PING/PONG link check with round-trip delay measurement.

Implemented optional Task 1 features:

- Manual DTR and RTS output control.
- CTS, DSR, RI, and DCD status display.

Task 1 test flow:

1. Open `Lab1_COM5.bat` and `Lab1_COM6.bat`.
2. Press `Open COM` in both windows.
3. Go to the `Task 1 - COM terminal` tab.
4. Send text from COM5 and verify it appears in the COM6 RX log.
5. Send text from COM6 and verify it appears in the COM5 RX log.
6. Press `Ping` and verify that the other side sends an automatic PONG and RTT is
   displayed.
7. Change the terminator and verify the last bytes in the hex log.

## Task 2: MODBUS-ASCII Master/Slave

Implemented obligatory features:

- MODBUS unit role selection: master or slave.
- Addressed transactions.
- Broadcast transactions using address `0`.
- Slave address range `1..247`.
- Query frame generation with:
  - address,
  - command,
  - data,
  - LRC checksum,
  - CRLF terminator.
- Frame reception and validation:
  - start character `:`,
  - CRLF terminator,
  - hexadecimal payload,
  - LRC checksum.
- Master transaction timeout in range `0..10 s`.
- Master retransmission count in range `0..5`.
- Inter-character frame continuity timeout in range `0..1 s`.
- Normal response and exception response handling.
- Hex preview for transmitted and received MODBUS frames.

Implemented custom application commands:

- Command `1`: master writes text to a slave. This also supports broadcast.
- Command `2`: master reads text from a slave. This is addressed-only.

Task 2 test flow:

1. Open `Lab1_COM5.bat` and `Lab1_COM6.bat`.
2. Press `Open COM` in both windows.
3. In the COM5 window, set Task 2 role to `master`.
4. In the COM6 window, set Task 2 role to `slave`, set slave address to `1`, and
   press `Apply slave settings`.
5. In the COM5 window, press `Write command 1`.
   - COM6 should display the received text.
   - COM5 should receive `OK`.
6. In the COM5 window, press `Read command 2`.
   - COM5 should display the slave response text.
7. In the COM5 window, press `Broadcast command 1`.
   - COM6 should process the text.
   - COM5 should not wait for a response.
8. Change the master address to a value different from the slave address and verify
   that the slave ignores the frame and the master times out/retries.

## CLI Fallback

The GUI is recommended for presentation, but CLI tools are still available.

List detected COM ports:

```powershell
.\scripts\list_ports.bat
```

Verify a null-modem link between COM5 and COM6:

```powershell
.\scripts\smoke_test_com5_com6.bat
```

Run Task 1 CLI terminals:

```powershell
.\scripts\task1_com5.bat
.\scripts\task1_com6.bat
```

Run Task 2 CLI master/slave:

```powershell
.\scripts\task2_slave_com6.bat
.\scripts\task2_master_com5.bat
```

Inside the CLI master:

```text
/write 1 Hello slave
/read 1
/broadcast Hello everyone
```

## Validation

The implementation was checked with:

```powershell
python -m unittest discover -s tests
python -m compileall csi_lab1 tests
.\scripts\smoke_test_com5_com6.bat
```

The COM5/COM6 link was also verified with a MODBUS-ASCII round trip at `9600 7E1`.

## Optional Features Not Implemented

The lab manual marks the following as optional, so they are not required for the
obligatory acceptance path and are not implemented here:

- binary hex-editor mode,
- binary file transmission,
- autobauding,
- MODBUS-RTU.
