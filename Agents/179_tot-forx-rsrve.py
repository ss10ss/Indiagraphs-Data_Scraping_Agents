def navigate_to_table(driver, wait):
    """
    Full flow from opening the site to the data table being loaded.
    Raises an Exception on failure at any step (caller handles the retry).
    """
    print("Opening page...")
    driver.get("https://data.rbi.org.in/DBIE/#/dbie/searchresult")

    print("Waiting explicitly for the page to settle...")
    time.sleep(12)
    driver.save_screenshot("step1_initial_page.png")

    try:
        alert = driver.switch_to.alert
        alert.dismiss()
        time.sleep(3)
    except Exception:
        pass

    print("Entering 'foreign exchange reserves' in the search box...")
    search_box = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@type='search' or @placeholder='Search']")))
    driver.execute_script("arguments[0].click();", search_box)
    driver.execute_script("arguments[0].value = '';", search_box)
    search_box.send_keys("foreign exchange reserves")
    time.sleep(3)
    driver.save_screenshot("step2_search_text_entered.png")

    print("Selecting 'all of the words' from the dropdown...")
    dropdown_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "select.dropdown")))
    select_filter = Select(dropdown_element)

    target_option = None
    for option in select_filter.options:
        option_text = (option.get_attribute("textContent") or "").strip().lower()
        if "all of the words" in option_text or "all these words" in option_text:
            target_option = option
            break

    if target_option is None:
        available = [opt.get_attribute("textContent").strip() for opt in select_filter.options]
        raise Exception(f"Could not find an 'all of the words' option in the dropdown. Available options: {available}")

    select_filter.select_by_value(target_option.get_attribute("value"))
    time.sleep(3)
    driver.save_screenshot("step3_dropdown_selected.png")

    print("Clicking the Update Results button...")
    update_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.search_button")))
    try:
        update_btn.click()
    except Exception:
        driver.execute_script("arguments[0].click();", update_btn)
    time.sleep(15)
    driver.save_screenshot("step4_results_updated.png")

    print("Clicking the 'Foreign Exchange Reserves' link...")
    report_link = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(text(), 'Foreign Exchange Reserves')]")))

    main_window = driver.current_window_handle
    try:
        report_link.click()
    except Exception:
        driver.execute_script("arguments[0].click();", report_link)

    print("Link clicked. Waiting dynamically for the new tab to open...")
    wait.until(lambda d: len(d.window_handles) > 1)
    driver.save_screenshot("step5_link_clicked.png")

    current_handles = driver.window_handles
    if len(current_handles) > 1:
        for handle in current_handles:
            if handle != main_window:
                driver.switch_to.window(handle)
                print("Successfully switched to the new tab.")
                break

    print("Waiting for the loading spinner to finish...")
    time.sleep(8)

    print("Locating and switching into the iframe...")
    iframe_element = wait.until(EC.presence_of_element_located((By.XPATH, "//iframe | //frame")))
    driver.switch_to.frame(iframe_element)
    print("Successfully switched inside the data iframe.")

    # NOTE: Foreign Exchange Reserves table loads directly without a "New Format" tab.
    # Skip tab selection and wait directly for the table elements.
    print("Waiting for table elements to be validated...")
    wait.until(EC.presence_of_all_elements_located((By.XPATH, "//td[@bid='5632']")))
    print("SUCCESS: Table loaded, elements found.")
    driver.save_screenshot("step6_data_tab_loaded.png")
