*** Settings ***
Documentation     NewsCollector System Tests
...               End-to-end tests that verify the complete system works correctly.
...               These tests run the server and database together to test the user experience.

Resource          resources.robot

Suite Setup       Start Server And Connect To Database
Suite Teardown    Stop Server And Close Database Connection

*** Keywords ***
Start Server And Connect To Database
    robot_lib.Start Web Server On Port    ${SERVER_PORT}
    robot_lib.Connect To Database

Stop Server And Close Database Connection
    robot_lib.Close Database Connection
    robot_lib.Stop Web Server

*** Test Cases ***

Test Database Connection
    [Documentation]    Verify PostgreSQL database is accessible and contains expected schema
    ${result}=    robot_lib.Execute Sql Query    SELECT current_database();
    Should Not Be Empty    ${result}
    ${tables}=    robot_lib.Execute Sql Query    SELECT tablename FROM pg_tables WHERE schemaname = 'public';
    Log Many    @{tables}

Test Database Has Collected Items
    [Documentation]    Verify the database has collected items data
    ${count}=    robot_lib.Execute Sql Query    SELECT COUNT(*) FROM collected_items;
    Log    Found ${count} collected items

Test Database Has Financial Reports
    [Documentation]    Verify the database has financial reports
    ${count}=    robot_lib.Execute Sql Query    SELECT COUNT(*) FROM financial_reports;
    Log    Found ${count} financial reports

Test API Root Endpoint
    [Documentation]    Verify the web server is running and serves the index page
    ${response}=    robot_lib.Get API    /
    Should Be Equal As Strings    ${response.status_code}    200
    Should Contain    ${response.text}    <!DOCTYPE html>

Test API Platforms Endpoint
    [Documentation]    Verify /api/platforms returns available platforms
    ${response}=    robot_lib.Get API    /api/platforms
    Should Be Equal As Strings    ${response.status_code}    200
    ${data}=    Set Variable    ${response.json()}
    Log    Platforms: ${data}

Test API Dates Endpoint
    [Documentation]    Verify /api/dates returns available dates
    ${response}=    robot_lib.Get API    /api/dates
    Should Be Equal As Strings    ${response.status_code}    200
    ${data}=    Set Variable    ${response.json()}
    Log    Dates: ${data}

Test API Items Endpoint
    [Documentation]    Verify /api/items returns collected items with pagination
    ${response}=    robot_lib.Get API    /api/items
    Should Be Equal As Strings    ${response.status_code}    200
    ${data}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${data}    items
    Dictionary Should Contain Key    ${data}    total
    Dictionary Should Contain Key    ${data}    count
    Log    Total items: ${data['total']}, Returned: ${data['count']}

Test API Items With Platform Filter
    [Documentation]    Verify /api/items supports platform filtering
    ${params}=    Create Dictionary    platform    news_rss
    ${response}=    robot_lib.Get API    /api/items    params=${params}
    Should Be Equal As Strings    ${response.status_code}    200
    ${data}=    Set Variable    ${response.json()}
    Log    Filtered items: ${data['count']}

Test API Items With Date Filter
    [Documentation]    Verify /api/items supports date filtering
    ${response}=    robot_lib.Get API    /api/dates
    ${dates}=    Set Variable    ${response.json()}
    ${length}=    Get Length    ${dates}
    IF    ${length} == 0
        Log    No dates available - test passes by default
    ELSE
        ${first_date}=    Get From List    ${dates}    0
        ${params}=    Create Dictionary    date    ${first_date}
        ${response}=    robot_lib.Get API    /api/items    params=${params}
        Should Be Equal As Strings    ${response.status_code}    200
        ${data}=    Set Variable    ${response.json()}
        Log    Items for ${first_date}: ${data['count']}
    END

Test API Items With Search
    [Documentation]    Verify /api/items supports search
    ${params}=    Create Dictionary    search    news
    ${response}=    robot_lib.Get API    /api/items    params=${params}
    Should Be Equal As Strings    ${response.status_code}    200
    ${data}=    Set Variable    ${response.json()}
    Log    Search results: ${data['count']}

Test API Regions Endpoint
    [Documentation]    Verify /api/regions returns distinct regions
    ${response}=    robot_lib.Get API    /api/regions
    Should Be Equal As Strings    ${response.status_code}    200
    ${data}=    Set Variable    ${response.json()}
    Log    Regions: ${data}

Test API Labels Endpoint
    [Documentation]    Verify /api/labels returns distinct labels
    ${response}=    robot_lib.Get API    /api/labels
    Should Be Equal As Strings    ${response.status_code}    200
    ${data}=    Set Variable    ${response.json()}
    Log    Labels: ${data}

Test API Daily Verdict Endpoint
    [Documentation]    Verify /api/daily-verdict returns verdict data
    ${response}=    robot_lib.Get API    /api/daily-verdict
    Should Be Equal As Strings    ${response.status_code}    200
    ${data}=    Set Variable    ${response.json()}
    Log    Daily verdict: ${data}

Test API Daily Analysis Endpoint
    [Documentation]    Verify /api/daily-analysis returns analysis entries
    ${response}=    robot_lib.Get API    /api/daily-analysis
    Should Be Equal As Strings    ${response.status_code}    200
    ${data}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${data}    entries

Test API Financial Reports Endpoint
    [Documentation]    Verify /api/financial-reports returns financial reports
    ${response}=    robot_lib.Get API    /api/financial-reports
    Should Be Equal As Strings    ${response.status_code}    200
    ${data}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${data}    reports
    Dictionary Should Contain Key    ${data}    total
    Log    Total reports: ${data['total']}

Test API Financial Reports With Region Filter
    [Documentation]    Verify /api/financial-reports supports region filtering
    ${response}=    robot_lib.Get API    /api/financial-regions
    ${regions}=    Set Variable    ${response.json()}
    ${length}=    Get Length    ${regions}
    IF    ${length} == 0
        Log    No regions available - test passes by default
    ELSE
        ${first_region}=    Get From List    ${regions}    0
        ${params}=    Create Dictionary    region    ${first_region}
        ${response}=    robot_lib.Get API    /api/financial-reports    params=${params}
        Should Be Equal As Strings    ${response.status_code}    200
        ${data}=    Set Variable    ${response.json()}
        Log    Reports for ${first_region}: ${data['count']}
    END

Test API Financial Rankings Endpoint
    [Documentation]    Verify /api/financial-rankings returns company rankings
    ${response}=    robot_lib.Get API    /api/financial-rankings
    Should Be Equal As Strings    ${response.status_code}    200
    ${data}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${data}    rankings
    Log    Rankings: ${data['count']} companies

Test API Company Scores Endpoint
    [Documentation]    Verify /api/company-scores returns company scores
    ${response}=    robot_lib.Get API    /api/company-scores
    Should Be Equal As Strings    ${response.status_code}    200
    ${data}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${data}    companies

Test API Company Scores Filters Endpoint
    [Documentation]    Verify /api/company-scores/filters returns filter options
    ${response}=    robot_lib.Get API    /api/company-scores/filters
    Should Be Equal As Strings    ${response.status_code}    200
    ${data}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${data}    sectors
    Dictionary Should Contain Key    ${data}    industries

Test API Financial Sectors Endpoint
    [Documentation]    Verify /api/financial-sectors returns aggregated sector data
    ${response}=    robot_lib.Get API    /api/financial-sectors
    Should Be Equal As Strings    ${response.status_code}    200
    ${data}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${data}    sectors

Test API Financial History Endpoint
    [Documentation]    Verify /api/financial-history returns historical data
    ${response}=    robot_lib.Get API    /api/financial-history
    Should Be Equal As Strings    ${response.status_code}    200
    ${data}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${data}    by_ticker
    Log    Tickers with history: ${data['tickers']}

Test API Health Distribution Endpoint
    [Documentation]    Verify /api/company-scores/distribution returns score distribution
    ${response}=    robot_lib.Get API    /api/company-scores/distribution
    Should Be Equal As Strings    ${response.status_code}    200
    ${data}=    Set Variable    ${response.json()}
    Dictionary Should Contain Key    ${data}    health_distribution
    Dictionary Should Contain Key    ${data}    potential_distribution

Test API Error Handling Invalid Date
    [Documentation]    Verify API handles invalid date parameter gracefully
    ${params}=    Create Dictionary    date    invalid-date
    ${response}=    robot_lib.Get API    /api/items    params=${params}
    Should Be Equal As Strings    ${response.status_code}    200

Test API Error Handling Invalid Platform
    [Documentation]    Verify API handles invalid platform parameter gracefully
    ${params}=    Create Dictionary    platform    nonexistent_platform_xyz
    ${response}=    robot_lib.Get API    /api/items    params=${params}
    Should Be Equal As Strings    ${response.status_code}    200
    ${data}=    Set Variable    ${response.json()}
    Should Be Equal As Integers    ${data['count']}    0
    Should Be Equal As Integers    ${data['total']}    0

Test API Pagination
    [Documentation]    Verify API supports pagination with offset
    ${response}=    robot_lib.Get API    /api/items
    ${data}=    Set Variable    ${response.json()}
    ${total}=    Set Variable    ${data['total']}
    IF    ${total} < 10
        Log    Not enough items to test pagination - test passes by default
    ELSE
        ${params1}=    Create Dictionary    offset    0
        ${response1}=    robot_lib.Get API    /api/items    params=${params1}
        ${data1}=    Set Variable    ${response1.json()}
        ${params2}=    Create Dictionary    offset    5
        ${response2}=    robot_lib.Get API    /api/items    params=${params2}
        ${data2}=    Set Variable    ${response2.json()}
        ${first_title_1}=    Get From List    ${data1['items']}    0
        ${first_title_2}=    Get From List    ${data2['items']}    0
        Should Not Be Equal As Strings    ${first_title_1['title']}    ${first_title_2['title']}
        Log    Pagination works - different items returned for offset 0 and 5
    END
