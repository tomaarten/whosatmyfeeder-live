# Who's At My Feeder LIVE!

A Python application for bird species detection and identification using Frigate NVR and TensorFlow Lite. Clear ripoff of mmcc-xx's work [Who's At My Feeder](https://github.com/mmcc-xx/WhosAtMyFeeder). The LIVE! variant has a number of improvements to the original and also a lot of nonsense. The recognition model has been updated to the latest version of Google AIY's [birds_V1 model](https://www.kaggle.com/models/google/aiy) and the image processing pipeline was updated so that it actually has a chance to be accurate (the original didn't properly crop the iamges). The web UI is now capable of showing the top 5 species matches for each detection, allowing the user to manually override erroneous detections. The functionality exists to confirm/review detections for accurarcy and to change the label of a species and have that info written to the database, but the display of that information is not implemented. In the end, the tool is surprisingly accurate. There will be plenty of false positives and missed detections, but it regularly gets 100+ correct detections per day in my setup.

And if it isn't obvious, this was poorly hacked together using AI tools including ChatGPT and Claude. Turns out they can get pretty close to a working application if you just paste the error codes you get back into the model repeatedly. Knowing that AI was involved should answer two questions you have: the first, how the hell did I pull this off by myself (a: I didn't) and why is this code so terrible (a: false promises of AI overlords).

## Overview

"Who's At My Feeder?" is a specialized application designed to work with [Frigate NVR](https://frigate.video/) to identify bird species at your backyard feeder or in your garden. The system:

1. Connects to Frigate's MQTT events stream to detect when birds are captured
2. Processes bird snapshots through a TensorFlow Lite model for species identification
3. Stores identification results in a SQLite database
4. Provides a web interface to browse, review, and analyze bird sightings

The application consists of two main components:
- A background service that processes bird detections from Frigate
- A Flask web UI for viewing and managing detections

## Prerequisites
- [Frigate NVR](https://frigate.video/) (properly configured with bird detection)
- Frigate-compatible camera [(official recomendations)](https://docs.frigate.video/frigate/hardware) positioned such that birds will appear large in its frame (mine is ~8" from a feeder)
- MQTT broker (mine is running through Home Assistant)
- Docker

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/YourUsername/whos-at-my-feeder.git
cd whos-at-my-feeder
```

### 2. Set up the configuration

Edit the configuration file at `config/config.yml` with the following structure:

```yaml
frigate:
  frigate_url: "localhost:5000"  # Frigate NVR URL
  mqtt_server: "localhost"       # MQTT broker address
  mqtt_auth: false               # Set to true if MQTT requires auth
  mqtt_username: ""              # Optional MQTT username
  mqtt_password: ""              # Optional MQTT password
  main_topic: "frigate"          # MQTT topic prefix for Frigate

classification:
  model: "models/bird_model.tflite"  # Path to TFLite model
  labels: "models/labels.txt"        # Path to labels file
  threshold: 0.5                     # Confidence threshold for detection

webui:
  host: "0.0.0.0"                    # Web UI host
  port: 7767                         # default Web UI port
```

### 3. Modify the whitelist file (optional)

Modify the file at `config/northeast_birds.txt` (or adjust path in code) with a list of bird species you want to include:

```
northern cardinal
american goldfinch
house finch
# Add comments with hashtag
```

### 4. Build the Docker image

Because I have no clue how this stuff works, I was just building the docker image manually. Open a terminal session in the `whosatmyfeeder-live` directory and run this command:

```bash
docker build -t whosatmyfeederlive . --debug
```

## Usage

### Start the application

```bash
docker compose up
```

This will start both the detection service and web interface. The web UI will be available at `http://localhost:7767` (or the configured host/port).

### Web Interface

- **Home Page**: Shows recent detections and a summary for the current day
- **Daily Summary**: View aggregated detection counts by hour for each species
- **Species View**: See all detections of a specific species for a given date
- **Hour View**: View all detections during a specific hour

## Model Training

The hope with the manual correction features is that the data you create could eventually be used to train your own model, specialized to your environment and bird population. Right now the program can log those manual reviews, but they're not really accessible in any way other than getting into sqlite3 on the command line.

## File Structure

```
├── config/
│   ├── config.yml                 # Configuration file
│   └── northeast_birds.txt        # Species whitelist
├── data/
│   └── speciesid.db               # Main SQLite database
├── models/
│   ├── bird_model.tflite          # TensorFlow Lite model
│   └── labels.txt                 # Model labels
├── static/
│   ├── css/
│   ├── js/
│   └── images/
├── templates/                     # HTML templates
├── birdnames.db                   # Species name mapping database
├── queries.py                     # Database query functions
├── speciesid.py                   # Main application
└── webui.py                       # Flask web interface
```

## Known Issues

- Lots
- of
- them


## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

Sure hope i'm not violating the things I ripped off...
