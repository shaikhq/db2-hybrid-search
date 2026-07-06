## 1. Install Db2 and create the instance
Anything before `su - db2inst1` runs as **root**.

```bash
# ===== Run as root =====
tar -xvf v12.1.5_linuxx64_server_dec.tar.gz     # extract install media (filename varies by version/edition — use your actual file)
cd server_dec
./db2_install                                   # install binaries (accept defaults)

useradd db2inst1                                # create instance owner
passwd db2inst1                                 # set its password

cd /opt/ibm/db2/V12.1/instance
./db2icrt -u db2inst1 -nosharedgroup db2inst1   # create instance (db2inst1 also = fenced user)

# ===== Run as db2inst1 =====
su - db2inst1
db2set DB2COMM=TCPIP                            # enable TCP/IP listener
db2 update dbm cfg using SVCENAME 50000         # set listener port
db2stop
db2start                                        # restart to apply
```

## 2. Create a sample database and run a test query
Run as `db2inst1`.

```bash
db2inst1$ db2sampl                                             # build the SAMPLE database
db2inst1$ db2 connect to sample                                # connect to it
db2inst1$ db2 "SELECT * FROM employee FETCH FIRST 5 ROWS ONLY" # returns 5 rows
```
