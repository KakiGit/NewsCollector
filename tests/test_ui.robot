*** Settings ***
Documentation     NewsCollector UI Tests using Playwright
...               End-to-end tests that verify the web UI works correctly.

Library           ./robot_lib.py

Suite Setup       Start Server And Open Browser
Suite Teardown    Close Browser And Stop Server

*** Variables ***
${SERVER_PORT}    8090
${BASE_URL}       http://localhost:${SERVER_PORT}

*** Keywords ***
Start Server And Open Browser
    robot_lib.Start Web Server On Port    ${SERVER_PORT}
    robot_lib.Open Browser    chromium    ${TRUE}
    robot_lib.Go To Url    ${BASE_URL}
    robot_lib.Wait For Load State    networkidle

Close Browser And Stop Server
    robot_lib.Close Browser
    robot_lib.Stop Web Server

*** Test Cases ***
Test Page Loads Successfully
    [Documentation]    Verify the main page loads without errors
    ${title}=    robot_lib.Get Page Title
    Should Not Be Empty    ${title}
    Log    Page title: ${title}

Test Navigation Tabs Exist
    [Documentation]    Verify main navigation elements are present
    # Check for main navigation buttons
    ${buttons_count}=    robot_lib.Get Element Count    button
    Should Be True    ${buttons_count} > 0
    Log    Found ${buttons_count} buttons

Test Home Tab Is Active By Default
    [Documentation]    Verify Home tab is displayed by default
    # Check for "Trending" text which is on home page
    robot_lib.Element Should Be Visible    text=Trending

Test Can Navigate To Financial Reports Tab
    [Documentation]    Verify clicking Financial Reports tab works
    robot_lib.Click Element    button:has-text("Financial Reports")
    robot_lib.Wait For Load State    networkidle
    Log    Navigated to Financial Reports tab

Test Financial Reports Tab Has Region Filter
    [Documentation]    Verify Financial Reports tab has Region filter
    robot_lib.Click Element    button:has-text("Financial Reports")
    robot_lib.Wait For Load State    networkidle
    robot_lib.Wait For Selector    text=Region / List    timeout=10000
    robot_lib.Element Should Be Visible    text=Region / List

Test Financial Reports Tab Has Status Filter
    [Documentation]    Verify Financial Reports tab has Status filter
    robot_lib.Click Element    button:has-text("Financial Reports")
    robot_lib.Wait For Load State    networkidle
    robot_lib.Element Should Be Visible    label:has-text("Status")

Test Financial Reports Tab Has Sort By
    [Documentation]    Verify Financial Reports tab has Sort by dropdown
    robot_lib.Click Element    button:has-text("Financial Reports")
    robot_lib.Wait For Load State    networkidle
    ${count}=    robot_lib.Get Element Count    label:has-text("Sort")
    Should Be True    ${count} > 0
    Log    Found ${count} Sort label(s)"

Test Search Input Exists On Home
    [Documentation]    Verify search input field exists on home page
    robot_lib.Wait For Load State    networkidle
    ${count}=    robot_lib.Get Element Count    input[placeholder*="Search"]
    Should Be True    ${count} > 0
    Log    Found ${count} search input(s)

Test Home Page Shows Data
    [Documentation]    Verify home page displays trending items or empty state
    robot_lib.Wait For Load State    networkidle
    # Just verify page has loaded with content
    ${html}=    robot_lib.Get Text    body
    Should Not Be Equal As Strings    ${html}    ${EMPTY}
    Log    Home page loaded successfully
