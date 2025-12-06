# PSD-to-JPG

A Python GUI application for batch converting Adobe Photoshop PSD files to JPG images using Adobe Photoshop automation.

## Features

- **Drag & Drop Interface**: Easily add PSD files by dragging and dropping or browsing folders
- **Batch Processing**: Convert multiple PSD files simultaneously
- **Progress Tracking**: Real-time progress bar and status updates
- **Database Storage**: Persistent file queue and processing status
- **Photoshop Integration**: Automates Photoshop to export PSD files as JPG
- **Cross-Platform**: Works on Windows (requires Adobe Photoshop)

## Requirements

- Python 3.8 or higher
- Adobe Photoshop (tested with Photoshop 2025)
- PySide6
- QtAwesome

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/mudrikam/PSD-to-JPG.git
   cd PSD-to-JPG
   ```

2. Install dependencies:
   ```bash
   pip install PySide6 qtawesome
   ```

3. Ensure Adobe Photoshop is installed on your system.

## Usage

1. Run the application:
   ```bash
   python psd_to_jpg.py
   ```

2. Select source folder containing PSD files
3. Select output folder for JPG files
4. Optionally, select Photoshop executable path
5. Add files via drag & drop or folder selection
6. Click "Start Processing" to begin conversion

## Configuration

The application saves configuration (Photoshop path, source/output folders) to `config.json` and uses a SQLite database (`database.db`) for file tracking.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Author

mudrikam