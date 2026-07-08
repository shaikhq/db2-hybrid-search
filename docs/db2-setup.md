# Install Db2 and prepare the instance

Steps before `su - db2inst1` run as **root**.

## 1. Install Db2 and create the instance

As **root** — extract the media (filename varies by version/edition), install the
binaries, create the instance owner, and create the instance:

```bash
tar -xvf v12.1.5_linuxx64_server_dec.tar.gz && cd server_dec
./db2_install                                    # accept defaults
useradd db2inst1 && passwd db2inst1
cd /opt/ibm/db2/V12.1/instance
./db2icrt -u db2inst1 -nosharedgroup db2inst1    # db2inst1 is also the fenced user
```

As **db2inst1** — enable the TCP/IP listener, set the port, and restart:

```bash
su - db2inst1
db2set DB2COMM=TCPIP
db2 update dbm cfg using SVCENAME 50000          # your instance may differ — see setup-and-run.md
db2stop && db2start
```

## 2. Create the sample database and test

As **db2inst1**:

```bash
db2sampl                                         # build the SAMPLE database
db2 connect to sample
db2 "SELECT * FROM employee FETCH FIRST 5 ROWS ONLY"   # should return 5 rows
```
