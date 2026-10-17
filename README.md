# Bits-AI-Demo-For-BIHAR

# Data Collection link -
                       - https://statedata.bihar.gov.in/dataLab/
                       - https://www.biharkrishi.in/
                       - https://horticulture.bihar.gov.in/
                       - https://bssca.co.in/SeedReports.aspx

                       - https://appeears.earthdatacloud.nasa.gov/
                       - https://www.earthdata.nasa.gov/data/catalog/lpcloud-mcd12q1-061#documents-and-resources

''' Agriculture information is already existing, such as MODIS LC, GLC and Globcover data sets.'''

# Some link of learing research paper -

### Satellite Data in Agricultural and EnvironmentalEconomics: Theory and Practice -
https://onlinelibrary.wiley.com/doi/epdf/10.1111/agec.70006

### Monitoring Horizontal and Vertical Cropping Pattern and Dynamics in Bihar
 https://www.academia.edu/44745746/Kumar_Jeganathan_2017_MonitoringHorizontalAndVertical_cropping_pattern_ISRS





 # Mongodb
 ''' To start the monogdb in local system, execute the command - sudo systemctl start mongod.
     To check the status use the command -  sudo systemctl status mongod '''

''' To create database in mongodb, run the command - mongosh (It will open mongodb shell)
                                   to show the database - show dbs
                                   To use specific database - use bitsAiDemoForBihar'''


## Running the mandi ingestion on Windows

Start Docker Desktop and ensure the MongoDB container is running:

```powershell
docker start bihar-mongodb
docker ps --filter "name=bihar-mongodb"
```

Activate the Python environment and run ingestion:

```powershell
.\.venv\Scripts\Activate.ps1
python ingest_mandi.py
```

A repeated run should process the available records but insert zero duplicates.
