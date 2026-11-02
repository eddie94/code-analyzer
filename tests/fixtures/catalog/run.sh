#!/bin/sh
TARGET="catalog.web:api"
exec uvicorn ${TARGET} --port 8100 --reload
