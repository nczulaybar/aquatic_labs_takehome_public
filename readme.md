## Requirements and Setup

This project was developed on python 3.12 with poetry.

If you have these installed, the project can setup from the top level directory with

```
poetry install
```

and run with 

```
script/server.sh
```

The server will create a db file in the project directory, or use a db file if one already exists.

Alternatively, a docker file is included which can built with

```
docker build . --tag NZ_app
```

and run with 

```
docker run -p 8000:8000 NZ_app
```

A full docker image exceeds 100 MB in size and so is not distributed directly here. The docker file creates the db within the container.

Unit tests can be run with 

```
poetry run pytest test_server.py
```

## Architecture

This project implements the Aquatic Labs takehome as a Python fastapi server.

Poetry and pytest are used in development.

api documentation is automatically generated at /docs when the server is running.

## Design Discussion

1. Couroutines for summarising and clearing data.

System requiemments dictated that data be summarised into one-minute and five-minute buckets after a certain period of time. Because summarisation would need to take place with the advancing of wall-clock time, even if no new data came in, it was determined that the logic for this would need to be done asynchronously in couroutines rather than synchronously when processing get or post requests. Couroutines, rather than threads, are the preferred pattern as fastapi defaults to an async-based single-threaded application. 

2. Use of DB to Stage Raw Measurements

While the requirements only require long term storage of 1-minute and 5-minute summarised data, it was also decided that the db be used for storing raw measurements as they accumulate for summarization. This was simpler than creating in-memory data structures that would potentially need to be lock-protected e.g., to prevent simultaneous writing of new measurements while past measurements are read for summarisation. The expected write rates of < 10 measurements per second are far below what can be handled by the sqlite instance, and scalability to hundreds of measurements per second is possible by batched db writing. This allows the application to remain fully stateless.

3. Handling of late insertions

It is expected that data generally arrive in-order and 'fresh' for summary generation. Data is summarised in 1 minute and 5 minute windows. If data for a given summary windows arrives after that summary has already been made, no attempt will be made to update old summaries.

Summaries with larger windows must naturally wait longer periods of time to collect data, so it is possible that measurements arrive 'in time' for the five minute summary but still too late for the one minute summary, for example. In the long run, only the long term summary is saved, so this is seen as a design feature (eventually-consistent, eventually-correct).

4. Handling of duplicate data.

There is expected to be one canonical measurement per time point. If 2 measurements are saved at the same time, an insert will fail. This indicates an error in the upstream data source, so this error will propagate to the HTTP endpoint (and presumably, bugsplat, datadog, etc.)

5. Performance

The relatively light read and write workloads of this application allow development to emphasize simplicity and readability over performance. For this reason, stats summarisation is performed in python rather than in SQL. Additionally, while a fully optimized db interface would use connection pooling and non-blocking connections, this implementation only implements non-blocking via aiosqlite but does not attempt to use a heavier library for connection pooling like sqlalchemy.

6. Testing of time-dependent server featuers

The server is required to summarise data every 1 minute and 5 minutes. There are multiple options to test this in unit tests, including:
1) Making these wait times configurtable, so that they can be shortened for test instances of the server. 
2) Proxying time checks to a fake clock object, which can be advanced in testing.

Pytest's monkeypatch feature makes implementing #2 very easy (at least compred to C++). This solution is detailed in the comments for fast_aiosleep in test_server.py

7. Testing and Validation

Beyond unit tests, the server was run for 1 hour with fake clients posting and getting measurements in the e2e_tests directory. Results were manually inspected for correctness. The e2e tests can be run with (in different termials) `python3 e2e_tests/read_summaries.py` and `python3 e2e_tests/post_measurements.py`. Both these scripts  read and write to 127.0.0.1:8000.

8. Database Performance, Concurrency and Error Handling

aiosqlite is based on sqlite3, which defaults to autocommit transaction behavior and sequential consistency. New connections are made frequently to simplify client code. For database locking conflicts, e.g., when 2 coroutines attempt to write simultaneously, brief retry is enabled on the db side. Try-catch logic surrounds DB calls in the summarization and cleanup co-routines, as uncaught db exceptions can kill these tasks without possibility of recovery.



