import base64
import os
from typing import Any
import requests
import time
import functions_framework
from datetime import datetime
from googleapiclient.discovery import build
from google.oauth2 import service_account
from google.cloud import storage
from instagrapi import Client


def download_images(image_urls: list[str], now_str: str) -> list[str]:
    """Downloads the images from the image URLs."""
    image_paths = []

    for idx, url in enumerate(image_urls):
        response = requests.get(url, timeout=30)
        file_path = f'image_{now_str}_{idx}.jpg'
        with open(file_path, 'wb') as file:
            file.write(response.content)
        image_paths.append(file_path)

    return image_paths


class ImageCreator:
    """Generates an image using the Midjourney API."""

    def __init__(self, go_api_key):
        self.go_api_key = go_api_key
        self.midjouenry_endpoint = 'https://api.midjourneyapi.xyz/mj/v2/'
        self.process_mode = 'fast'


    def _get_header(self):
        return {
            'Content-Type': 'application/json',
            'X-API-KEY': self.go_api_key
        }

    def send_prompt(self, prompt: str, aspect_ratio: str = '1:1') -> str:
        """Creates a task to generate an image."""
        data = {
            'prompt': prompt,
            'process_mode': self.process_mode,
            'aspect_ratio': aspect_ratio,
        }

        response = requests.post(self.midjouenry_endpoint + 'imagine',
                                 headers=self._get_header(),
                                 json=data,
                                 timeout=10)

        if response.status_code == 200:
            message = response.json()
            if message['status'] == 'success':
                return message['task_id']
            else:
                raise ValueError(message)
        raise ValueError(response.status_code)

    def get_image(self, task_id: str) -> str:
        """Gets the image URL from the task."""
        data = {
            'task_id': task_id
        }

        while True:
            print('Waiting 30 seconds...')
            time.sleep(30)
            response = requests.post(self.midjouenry_endpoint + 'fetch',
                                    headers=self._get_header(),
                                    json=data,
                                    timeout=10)

            if response.status_code == 200:
                message = response.json()
                if message['status'] == 'processing':
                    continue
                elif message['status'] == 'finished':
                    return message['task_result']['image_url']
                else:
                    raise ValueError(message)
            raise ValueError(response.status_code)

    def upscale(self, task_id: str, index: int) -> str:
        """Upscales the image."""
        data = {
            'origin_task_id': task_id,
            'index': str(index),
        }

        response = requests.post(self.midjouenry_endpoint + 'upscale',
                                headers=self._get_header(),
                                json=data,
                                timeout=10)

        if response.status_code == 200:
            message = response.json()
            if message['status'] == 'success':
                return message['task_id']
            else:
                raise ValueError(message)
        raise ValueError(response.status_code)


class GoogleSheetManager:
    """Manages the Google Sheets API."""

    def __init__(self, sheet_id, credentials_file):
        self.sheet_id = sheet_id
        credentials = service_account.Credentials.from_service_account_file(credentials_file)  
        self.service = build('sheets', 'v4', credentials=credentials)

    def read_sheet(self, sheet_name: str) -> list[list[Any]]:
        """Reads the values from a Google Sheet."""
        range_ = f'{sheet_name}!A1:Z'
        result = self.service.spreadsheets().values().get(
            spreadsheetId=self.sheet_id,
            range=range_,
        ).execute()
        values = result.get('values', [])
        return values # containing both the header and all the rows

    def write_sheet(self, sheet_name: str, values: list[list[Any]]):
        """Writes the values to a Google Sheet."""
        range_ = f'{sheet_name}!A1:Z'
        result = self.service.spreadsheets().values().update(
            spreadsheetId=self.sheet_id,
            range=range_,
            valueInputOption='USER_ENTERED',
            body={'values': values}
        ).execute()
        return result.get('updatedCells')


def generate_images(go_api_key: str, prompt: str, now_str: str) -> None:
    """Generates images using the Midjourney API."""
    client = ImageCreator(go_api_key)
    image_task_id = client.send_prompt(prompt)
    print(f'Task ID to generate images: {image_task_id}')
    image_url = client.get_image(image_task_id)
    print(f'4 Images URL: {image_url}')

    print('Upscaling...')
    upscaling_task_ids = []
    upscaled_image_urls = []
    for idx in range(1, 5):
        time.sleep(1)
        upscaling_task_id = client.upscale(image_task_id, idx)
        print(f'Task ID to upscale: {upscaling_task_id}')
        upscaling_task_ids.append(upscaling_task_id)

    for upscaling_task_id in upscaling_task_ids:
        upscaled_image_url = client.get_image(upscaling_task_id)
        print(f'Upscaled images URL: {upscaled_image_url}')
        upscaled_image_urls.append(upscaled_image_url)

    upscaled_image_files = download_images(upscaled_image_urls, now_str)
    return upscaled_image_files


def load_instagram(username: str, password: str, image_files: list[str],
                   description: str, default_tags: str, tags: str):
    """Loads images to Instagram."""
    # Login to Instagram
    caption = description
    for tag in tags.split(','):
        caption += ' #' + tag.strip().replace(' ', '')

    caption += default_tags
    cl = Client()
    cl.login(username, password)
    cl.album_upload(image_files, caption=caption)
    cl.logout()


# Triggered from a message on a Cloud Pub/Sub topic.
@functions_framework.cloud_event
def generate_images_load_instagram(cloud_event):
    """Triggered from a message on a Cloud Pub/Sub topic."""
    # Print out the data from Pub/Sub, to prove that it worked
    start = time.time()
    print(base64.b64decode(cloud_event.data["message"]["data"]))
    sheet_id = os.environ['SHEET_ID']
    sheet_name = os.environ['SHEET_NAME']
    bucket_name = os.environ['BUCKET']
    default_tags = os.environ.get('DEFAULT_TAGS', '')
    insta_username = os.environ['INSTAGRAM_USERNAME']
    insta_password = os.environ['INSTAGRAM_PASSWORD']
    go_api_key = os.environ['GO_API_KEY']

    sheet_manager = GoogleSheetManager(sheet_id, 'credentials.json')
    storage_client = storage.Client.from_service_account_json('credentials.json')
    bucket = storage_client.get_bucket(bucket_name)

    values = sheet_manager.read_sheet(sheet_name)
    now = datetime.now()
    now_str = now.strftime('%Y_%m_%d_%H_%M')
    today_str = now.strftime('%Y/%m')
    for row in values[1:]:
        if len(row) != len(values[0]):
            row_id, prompt, description, tags = row
            image_files = generate_images(go_api_key, prompt, now_str)
            load_instagram(insta_username, insta_password, image_files, description, default_tags, tags)
            row.append(now_str)
            for image_file in image_files:
                blob = bucket.blob(f'{today_str}/{image_file}')
                blob.upload_from_filename(image_file)
            break
    sheet_manager.write_sheet('Prompts', values)

    duration = time.time() - start
    print(f'Duration: {duration}')
