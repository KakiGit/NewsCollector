*** Settings ***
Documentation     Shared resources for NewsCollector system tests
Library            Collections
Library            ./robot_lib.py

*** Variables ***
${BASE_URL}            http://localhost:8090
${SERVER_PORT}        8090
${DB_HOST}             newscollector_db
${DB_PORT}            5432
${DB_NAME}            newscollector
${DB_USER}            newscollector
${DB_PASSWORD}        localdevpass
