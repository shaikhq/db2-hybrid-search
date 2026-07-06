## 1. Install Db2 and create the instance

Anything before `su - db2inst1` runs as **root**.

**Run as root**

Extract install media (filename varies by version/edition — use your actual file):

```bash
tar -xvf v12.1.5_linuxx64_server_dec.tar.gz
```

```bash
cd server_dec
```

Install binaries (accept defaults):

```bash
./db2_install
```

Create instance owner:

```bash
useradd db2inst1
```

Set its password:

```bash
passwd db2inst1
```

```bash
cd /opt/ibm/db2/V12.1/instance
```

Create instance (db2inst1 also = fenced user):

```bash
./db2icrt -u db2inst1 -nosharedgroup db2inst1
```

**Run as db2inst1**

```bash
su - db2inst1
```

Enable TCP/IP listener:

```bash
db2set DB2COMM=TCPIP
```

Set listener port:

```bash
db2 update dbm cfg using SVCENAME 50000
```

Restart to apply:

```bash
db2stop
```

```bash
db2start
```

## 2. Create a sample database and run a test query

Run as `db2inst1`.

Build the SAMPLE database:

```bash
db2sampl
```

Connect to it:

```bash
db2 connect to sample
```

Returns 5 rows:

```bash
db2 "SELECT * FROM employee FETCH FIRST 5 ROWS ONLY"
```
