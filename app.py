import os
import json
import io
from flask import Flask, request, send_file, jsonify
from PIL import Image
import requests

app = Flask(__name__)

# --- Configuration ---
ITEM_DATA_FILE = 'main.json'
BACKGROUND_FOLDER = 'background'
EXTERNAL_ITEM_API_BASE = 'https://free-fire-items.vercel.app/item-image'
API_KEY = 'NRCODEX' # Aapka API key
DEFAULT_BACKGROUND_IMAGE = 'background/Default.png' # Fallback background image

# Global variable to store item data (loaded once for efficiency)
item_data = None

def load_item_data():
    """Loads item data from main.json."""
    global item_data
    if item_data is not None:
        return item_data

    file_path = os.path.join(os.path.dirname(__file__), ITEM_DATA_FILE)
    if not os.path.exists(file_path):
        app.logger.error(f"Error: {ITEM_DATA_FILE} not found at {file_path}")
        return None

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            item_data = json.load(f)
            app.logger.info(f"Successfully loaded {len(item_data)} items from {ITEM_DATA_FILE}.")
            return item_data
    except json.JSONDecodeError as e:
        app.logger.error(f"Error decoding JSON from {ITEM_DATA_FILE}: {e}")
        return None
    except Exception as e:
        app.logger.error(f"An unexpected error occurred while loading {ITEM_DATA_FILE}: {e}")
        return None

# Load data when the app starts
with app.app_context():
    load_item_data()

@app.route('/item-image/<int:itemid>', methods=['GET'])
def get_combined_item_image(itemid):
    """
    Fetches item details, combines with a rare-based background,
    and returns the combined image.
    """
    if item_data is None:
        return jsonify({"error": "Item data not loaded. Check server logs."}), 500

    # 1. Find item details from main.json
    item_found = None
    for item in item_data:
        if item.get("Id") == itemid:
            item_found = item
            break

    if not item_found:
        app.logger.warning(f"Item with ID {itemid} not found in {ITEM_DATA_FILE}")
        return jsonify({"error": f"Item with ID {itemid} not found."}), 404

    rare_type = item_found.get("Rare", "Default") # Default if 'Rare' key is missing

    # 2. Load background image based on 'Rare' type
    background_image_path = os.path.join(os.path.dirname(__file__), BACKGROUND_FOLDER, f'{rare_type}.png')
    
    if not os.path.exists(background_image_path):
        app.logger.warning(f"Background image for Rare type '{rare_type}' not found. Using default.")
        background_image_path = os.path.join(os.path.dirname(__file__), DEFAULT_BACKGROUND_IMAGE)
        if not os.path.exists(background_image_path):
             app.logger.error(f"Default background image not found at {DEFAULT_BACKGROUND_IMAGE}.")
             return jsonify({"error": "Background image not found and default is missing."}), 500

    try:
        background = Image.open(background_image_path).convert("RGBA")
    except Exception as e:
        app.logger.error(f"Error loading background image {background_image_path}: {e}")
        return jsonify({"error": "Could not load background image."}), 500

    # 3. Fetch item image from external API
    external_api_url = f"{EXTERNAL_ITEM_API_BASE}?id={itemid}&key={API_KEY}"
    try:
        response = requests.get(external_api_url, stream=True)
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

        item_image_bytes = io.BytesIO(response.content)
        item_image = Image.open(item_image_bytes).convert("RGBA")
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Error fetching item image from external API for ID {itemid}: {e}")
        return jsonify({"error": f"Could not fetch item image from external source. Error: {e}"}), 502
    except Image.UnidentifiedImageError:
        app.logger.error(f"External API returned unidentifiable image for ID {itemid}.")
        return jsonify({"error": "External API did not return a valid image."}), 502
    except Exception as e:
        app.logger.error(f"An unexpected error occurred while processing external image for ID {itemid}: {e}")
        return jsonify({"error": "An unexpected error occurred with external image."}), 500

    # 4. Resize and overlay item image onto background
    bg_width, bg_height = background.size

    # Calculate target size for item image (e.g., 70% of background's smaller dimension)
    # Maintain aspect ratio
    target_max_dimension = min(bg_width, bg_height) * 0.7
    item_width, item_height = item_image.size

    if item_width > target_max_dimension or item_height > target_max_dimension:
        # Scale down if too large
        scale_factor = target_max_dimension / max(item_width, item_height)
        new_item_width = int(item_width * scale_factor)
        new_item_height = int(item_height * scale_factor)
        item_image = item_image.resize((new_item_width, new_item_height), Image.LANCZOS)
    elif item_width < target_max_dimension * 0.5 and item_height < target_max_dimension * 0.5:
        # Scale up slightly if too small (optional, adjust factor as needed)
        scale_factor = (target_max_dimension * 0.6) / max(item_width, item_height)
        new_item_width = int(item_width * scale_factor)
        new_item_height = int(item_height * scale_factor)
        if new_item_width > item_width or new_item_height > item_height: # Only scale up if actually increasing size
            item_image = item_image.resize((new_item_width, new_item_height), Image.LANCZOS)


    # Calculate position to center the item image
    paste_x = (bg_width - item_image.width) // 2
    paste_y = (bg_height - item_image.height) // 2

    # Create a blank transparent image to paste the item image onto
    # This allows using alpha_composite correctly
    temp_image = Image.new("RGBA", background.size, (0, 0, 0, 0))
    temp_image.paste(item_image, (paste_x, paste_y), item_image)

    # Composite the background and the item image
    combined_image = Image.alpha_composite(background, temp_image)


    # 5. Return the combined image as PNG
    img_byte_arr = io.BytesIO()
    combined_image.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0) # Go to the beginning of the stream

    app.logger.info(f"Successfully generated image for Item ID: {itemid}, Rare: {rare_type}")
    return send_file(img_byte_arr, mimetype='image/png', as_attachment=False, download_name=f'item_{itemid}.png')

if __name__ == '__main__':
    # For development, run in debug mode
    # In production, use a WSGI server like Gunicorn/Waitress
    app.run(debug=True, port=5000)
    # Ensure item data is loaded even if run directly without app context block
    # This check is more for robustness if app.app_context() is removed
    if item_data is None:
        load_item_data()