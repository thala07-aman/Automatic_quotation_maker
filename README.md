# 🧳 Multi-City Travel Quotation Builder

An intelligent travel quotation system that generates comprehensive, multi-city travel plans with automated pricing, sightseeing suggestions, and day-by-day itineraries using AI.

## 📋 Overview

This application streamlines the process of creating professional travel quotations for multi-city trips. It combines pricing data from Excel files with AI-powered sightseeing recommendations and itinerary generation to produce detailed, customizable travel plans.

## ✨ Features

### Core Functionality
- **Multi-City Planning**: Support for multiple cities in a single trip with customizable days per city
- **Dynamic Pricing**: Excel-based pricing engine for hotels and car rentals
- **Hotel Options**: Three-tier hotel selection (Best Value, Option B, Option C) with AI-generated recommendations
- **Room Configuration**: Flexible room allocation with extra bed support
- **Car Rental Integration**: Optional car rental with multiple vehicle types
- **Price Override**: Manual price adjustment capability for custom negotiations

### AI-Powered Features
- **Sightseeing Generation**: AI-curated list of attractions using Groq's Llama 3.3 70B model
- **Itinerary Builder**: Automated day-by-day activity planning
- **Hotel Recommendations**: AI-generated explanations for hotel choices
- **Custom Notes**: Per-city recommendations and special instructions

### Output & Storage
- **PDF Generation**: Professional quotation documents with complete trip details
- **Database Storage**: SQLite-based quotation history with unique quotation numbers
- **Quotation Tracking**: Format: `QT-YYYY-NNNN` (e.g., QT-2026-0001)

## 🛠️ Technology Stack

- **Frontend**: Streamlit
- **AI/LLM**: Groq API (Llama 3.3 70B Versatile)
- **Database**: SQLite
- **Data Processing**: Pandas
- **PDF Generation**: ReportLab
- **Excel Handling**: OpenPyXL

## 📦 Installation

### Prerequisites
- Python 3.8+
- Groq API Key

### Setup

1. **Clone the repository**
```bash
git clone <repository-url>
cd Automatic_quotation_maker
```

2. **Install dependencies**
```bash
pip install -r requirements.txt
```

3. **Configure environment variables**

Create a `.env` file in the project root:
```env
GROQ_API_KEY=your_groq_api_key_here
```

4. **Run the application**
```bash
streamlit run App/travel_plan_app.py
```

## 📊 Excel File Format

The application requires an Excel file with two sheets:

### Hotels Sheet
| Column | Description |
|--------|-------------|
| City | City name |
| Hotel_Name | Name of the hotel |
| Star | Star rating (2, 3, 4, or 5) |
| Price_Per_Night_Per_Person | Price per person per night |

### CarRental Sheet
| Column | Description |
|--------|-------------|
| car_type | Type of vehicle (e.g., Sedan, SUV) |
| price_per_day | Daily rental price |

## 🚀 Usage

### Step 1: Upload Pricing Data
- Upload your Excel file containing hotel and car rental pricing

### Step 2: Enter Customer Details
- Customer name (required)
- Select cities in travel order
- Enter days per city (comma-separated)

### Step 3: Configure Trip Parameters
- Number of travelers
- Hotel category (2-5 stars)
- Sightseeing places per city
- Optional notes per city

### Step 4: Customize Per City
For each city, configure:
- **Hotel Selection**: Choose from 3 AI-recommended options
- **Room Configuration**: Number of rooms and extra beds
- **Price Override**: Adjust hotel pricing if needed
- **Car Rental**: Optional vehicle selection

### Step 5: Generate & Finalize
- Review the complete quotation
- Finalize to generate quotation number
- Download PDF with unique filename

## 📁 Project Structure

```
Automatic_quotation_maker/
├── App/
│   ├── travel_plan_app.py      # Main Streamlit application
│   ├── database.py              # SQLite database operations
│   ├── pricing_engine.py        # Pricing calculations and data loading
│   ├── itinerary_builder.py    # AI-powered itinerary generation
│   ├── generate_sightseeing.py # AI-powered sightseeing suggestions
│   └── quotations.db            # SQLite database (auto-generated)
├── Test/
│   └── test/
│       ├── test_combined.py
│       └── test.py
├── requirements.txt
└── README.md
```

## 🔧 Key Components

### Database Module (`database.py`)
- Quotation storage and retrieval
- Automatic schema migration
- JSON serialization with numpy/pandas type handling
- Unique quotation number generation

### Pricing Engine (`pricing_engine.py`)
- Excel data loading and validation
- Hotel filtering by city and star rating
- Car rental options management
- Price calculation logic

### Itinerary Builder (`itinerary_builder.py`)
- AI-powered day-by-day planning
- Activity distribution across days
- Cost allocation per day
- JSON-structured output

### Sightseeing Generator (`generate_sightseeing.py`)
- AI-curated attraction lists
- Factual, concise descriptions
- Custom note integration
- Configurable place limits

## 💡 Features in Detail

### Quotation Number System
- Format: `QT-YYYY-NNNN`
- Auto-incremented internal ID
- Year-based organization
- Unique constraint enforcement

### Price Override System
- Base price from Excel
- Manual override capability
- Visual indication of overrides
- Preserved in quotation history

### Room Configuration
- Automatic room calculation (travelers ÷ 2)
- Extra bed support with custom pricing
- Per-city configuration
- Cost breakdown display

### AI Integration
- Temperature: 0 (deterministic) for itineraries
- Temperature: 0.3 for hotel recommendations
- JSON-only responses
- Error handling and fallbacks

## 📝 Output Format

### PDF Quotation Includes:
- Customer details and trip summary
- Grand total cost
- Per-city breakdown:
  - Hotel details and costs
  - Car rental information
  - Room configuration
  - Custom notes
  - Sightseeing list with descriptions
  - Day-by-day itinerary with costs

### Database Storage:
- Quotation number
- Customer name
- Cities visited
- Total cost
- Creation timestamp
- Complete JSON data

## 🔒 Data Safety

- SQLite database with ACID compliance
- JSON serialization for complex data
- Type-safe conversions (numpy/pandas → Python native)
- Schema migration support
- Thread-safe database connections

## 🐛 Error Handling

- Excel format validation
- Missing data checks
- AI response parsing with fallbacks
- Database constraint enforcement
- User-friendly error messages

## 🚧 Known Limitations

- Single-threaded Streamlit session state
- Requires manual Excel file upload per session
- AI responses depend on Groq API availability
- PDF generation uses basic ReportLab styling

## 🔮 Future Enhancements

- [ ] Multi-language support
- [ ] Advanced PDF templates
- [ ] Email quotation delivery
- [ ] Customer portal
- [ ] Payment integration
- [ ] Real-time pricing updates
- [ ] Image gallery for hotels
- [ ] Map integration for itineraries

## 📄 License

[Add your license information here]

## 👥 Contributors

[Add contributor information here]

## 📞 Support

For issues, questions, or contributions, please [add contact/issue tracking information].

---

**Built with ❤️ for travel professionals**