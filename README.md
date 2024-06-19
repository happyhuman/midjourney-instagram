# midjourney-instagram
A pipeline to generate beautiful images and upload them to instagram

This python code is a Google Cloud Function which uses GoApi to make a call to MidJourney
and generate 4 new images, given a prompt. It then uploads these 4 images as a new album
to an instagram account. It also copies the generates images into a Google Cloud Storage
bucket as a backup.
