/* ========================================================================== */
/* COMPREHENSIVE SAS TEST PROGRAM                                             */
/* Purpose: Test various SAS constructs for field lineage tracking           */
/* Contains: 1000+ lines with diverse SAS operations and table structures    */
/* ========================================================================== */

/* -------------------------------------------------------------------------- */
/* SECTION 1: BASIC DATA LOADING AND CLEANING                                */
/* -------------------------------------------------------------------------- */

/* Step 1.1: Load raw customer data */
DATA raw_customers;
    SET source_customers;
    
    /* Basic field assignments */
    customer_key = customer_id;
    record_date = TODAY();
    
    /* String operations */
    full_name = TRIM(first_name) || ' ' || TRIM(last_name);
    name_upper = UPCASE(full_name);
    name_lower = LOWCASE(full_name);
    first_initial = SUBSTR(first_name, 1, 1);
    last_initial = SUBSTR(last_name, 1, 1);
    initials = TRIM(first_initial) || '.' || TRIM(last_initial) || '.';
    
    /* Email validation and cleaning */
    email_clean = STRIP(LOWCASE(email));
    email_domain = SCAN(email_clean, 2, '@');
    email_username = SCAN(email_clean, 1, '@');
    has_valid_email = (INDEX(email_clean, '@') > 0);
    
    /* Phone number standardization */
    phone_clean = COMPRESS(phone, '()-. ');
    phone_area_code = SUBSTR(phone_clean, 1, 3);
    phone_exchange = SUBSTR(phone_clean, 4, 3);
    phone_number = SUBSTR(phone_clean, 7, 4);
    phone_formatted = '(' || phone_area_code || ') ' || phone_exchange || '-' || phone_number;
    
    /* Address parsing */
    address_upper = UPCASE(address);
    city_proper = PROPCASE(city);
    state_upper = UPCASE(state);
    zip_5digit = SUBSTR(zipcode, 1, 5);
    zip_plus4 = SUBSTR(zipcode, 6, 4);
    
    /* Date calculations */
    registration_date = input(reg_date_char, YYMMDD10.);
    days_since_registration = INTCK('DAY', registration_date, TODAY());
    years_since_registration = INTCK('YEAR', registration_date, TODAY());
    months_since_registration = INTCK('MONTH', registration_date, TODAY());
    
    /* Age calculations */
    birth_date = input(birth_date_char, YYMMDD10.);
    current_age = FLOOR((TODAY() - birth_date) / 365.25);
    age_group = FLOOR(current_age / 10) * 10;
    
    /* Customer classification */
    is_senior = (current_age >= 65);
    is_adult = (current_age >= 18 AND current_age < 65);
    is_minor = (current_age < 18);
    
    /* Demographic flags */
    age_category = '';
    IF current_age < 18 THEN age_category = 'Minor';
    ELSE IF current_age < 30 THEN age_category = 'Young Adult';
    ELSE IF current_age < 50 THEN age_category = 'Middle Age';
    ELSE IF current_age < 65 THEN age_category = 'Senior Adult';
    ELSE age_category = 'Senior';
    
RUN;

/* Step 1.2: Load and process product catalog */
DATA raw_products;
    SET source_products;
    
    /* Product identifiers */
    product_key = product_id;
    sku_clean = STRIP(UPCASE(sku));
    
    /* Product name processing */
    product_name_clean = PROPCASE(product_name);
    product_name_upper = UPCASE(product_name);
    product_name_length = LENGTH(product_name_clean);
    
    /* Category and subcategory */
    category_upper = UPCASE(category);
    subcategory_upper = UPCASE(subcategory);
    full_category = TRIM(category_upper) || ' - ' || TRIM(subcategory_upper);
    
    /* Price calculations */
    base_price = unit_price;
    tax_rate = 0.08;
    tax_amount = base_price * tax_rate;
    price_with_tax = base_price + tax_amount;
    
    /* Pricing tiers */
    price_tier = '';
    IF base_price < 10 THEN price_tier = 'Budget';
    ELSE IF base_price < 50 THEN price_tier = 'Standard';
    ELSE IF base_price < 100 THEN price_tier = 'Premium';
    ELSE price_tier = 'Luxury';
    
    /* Inventory metrics */
    stock_level = current_stock;
    reorder_point = minimum_stock * 1.5;
    stock_status = '';
    IF stock_level <= 0 THEN stock_status = 'Out of Stock';
    ELSE IF stock_level < reorder_point THEN stock_status = 'Low Stock';
    ELSE stock_status = 'In Stock';
    
    /* Cost and margin calculations */
    unit_cost = cost_price;
    profit_per_unit = base_price - unit_cost;
    profit_margin = (profit_per_unit / base_price) * 100;
    markup_percentage = (profit_per_unit / unit_cost) * 100;
    
    /* Discounting logic */
    standard_discount_rate = 0.10;
    bulk_discount_rate = 0.15;
    clearance_discount_rate = 0.30;
    
    /* Product metrics */
    weight_kg = weight_pounds / 2.20462;
    dimensions_metric = length_cm || 'x' || width_cm || 'x' || height_cm;
    volume_cubic_cm = length_cm * width_cm * height_cm;
    shipping_weight = weight_kg + 0.5;
    
    /* Supplier information */
    supplier_code = UPCASE(supplier_id);
    lead_time_days = supplier_lead_time;
    safety_stock = CEIL(lead_time_days * average_daily_sales);
    
RUN;

/* Step 1.3: Load transaction data */
DATA raw_transactions;
    SET source_transactions;
    
    /* Transaction identifiers */
    transaction_key = transaction_id;
    order_key = order_id;
    
    /* Date and time processing */
    transaction_date = input(trans_date_char, YYMMDD10.);
    transaction_datetime = input(trans_datetime_char, DATETIME20.);
    transaction_year = YEAR(transaction_date);
    transaction_month = MONTH(transaction_date);
    transaction_day = DAY(transaction_date);
    transaction_quarter = QTR(transaction_date);
    
    /* Day of week */
    transaction_dow = WEEKDAY(transaction_date);
    transaction_dow_name = '';
    IF transaction_dow = 1 THEN transaction_dow_name = 'Sunday';
    ELSE IF transaction_dow = 2 THEN transaction_dow_name = 'Monday';
    ELSE IF transaction_dow = 3 THEN transaction_dow_name = 'Tuesday';
    ELSE IF transaction_dow = 4 THEN transaction_dow_name = 'Wednesday';
    ELSE IF transaction_dow = 5 THEN transaction_dow_name = 'Thursday';
    ELSE IF transaction_dow = 6 THEN transaction_dow_name = 'Friday';
    ELSE transaction_dow_name = 'Saturday';
    
    /* Time components */
    transaction_hour = HOUR(transaction_datetime);
    transaction_minute = MINUTE(transaction_datetime);
    
    /* Time of day classification */
    time_of_day = '';
    IF transaction_hour < 6 THEN time_of_day = 'Night';
    ELSE IF transaction_hour < 12 THEN time_of_day = 'Morning';
    ELSE IF transaction_hour < 17 THEN time_of_day = 'Afternoon';
    ELSE IF transaction_hour < 21 THEN time_of_day = 'Evening';
    ELSE time_of_day = 'Night';
    
    /* Quantity and amount calculations */
    quantity_ordered = quantity;
    unit_price_paid = unit_price;
    subtotal_amount = quantity_ordered * unit_price_paid;
    
    /* Discount calculations */
    discount_rate_applied = discount_percent / 100;
    discount_amount = subtotal_amount * discount_rate_applied;
    amount_after_discount = subtotal_amount - discount_amount;
    
    /* Tax calculations */
    tax_rate_applied = tax_rate;
    tax_amount_calculated = amount_after_discount * tax_rate_applied;
    
    /* Shipping calculations */
    shipping_fee = shipping_cost;
    handling_fee = 2.50;
    total_shipping = shipping_fee + handling_fee;
    
    /* Total amount */
    transaction_total = amount_after_discount + tax_amount_calculated + total_shipping;
    
    /* Payment information */
    payment_method_clean = PROPCASE(payment_method);
    is_credit_card = (INDEX(UPCASE(payment_method), 'CREDIT') > 0);
    is_debit_card = (INDEX(UPCASE(payment_method), 'DEBIT') > 0);
    is_cash = (INDEX(UPCASE(payment_method), 'CASH') > 0);
    is_digital_payment = (INDEX(UPCASE(payment_method), 'PAYPAL') > 0 OR 
                          INDEX(UPCASE(payment_method), 'VENMO') > 0);
    
    /* Transaction status */
    status_upper = UPCASE(status);
    is_completed = (status_upper = 'COMPLETED');
    is_pending = (status_upper = 'PENDING');
    is_cancelled = (status_upper = 'CANCELLED');
    is_refunded = (status_upper = 'REFUNDED');
    
    /* Channel information */
    sales_channel = UPCASE(channel);
    is_online = (sales_channel = 'ONLINE');
    is_store = (sales_channel = 'STORE');
    is_mobile = (sales_channel = 'MOBILE');
    is_phone = (sales_channel = 'PHONE');
    
RUN;

/* -------------------------------------------------------------------------- */
/* SECTION 2: DATA INTEGRATION AND MERGING                                   */
/* -------------------------------------------------------------------------- */

/* Step 2.1: Merge customers with transactions */
DATA customer_transactions;
    MERGE raw_customers (IN=in_cust)
          raw_transactions (IN=in_trans);
    BY customer_key;
    
    /* Merge indicators */
    has_customer_data = in_cust;
    has_transaction_data = in_trans;
    is_matched = (in_cust AND in_trans);
    
    /* Customer transaction metrics */
    IF is_matched THEN DO;
        /* Revenue per transaction */
        revenue_amount = transaction_total;
        
        /* Customer lifetime value component */
        transaction_contribution = revenue_amount;
        
        /* Frequency indicators */
        is_first_purchase = (days_since_registration < 30 AND transaction_date <= registration_date + 30);
        is_repeat_customer = (days_since_registration > 30);
        
        /* Recency metrics */
        days_since_last_purchase = INTCK('DAY', transaction_date, TODAY());
        recency_category = '';
        IF days_since_last_purchase < 30 THEN recency_category = 'Active';
        ELSE IF days_since_last_purchase < 90 THEN recency_category = 'Recent';
        ELSE IF days_since_last_purchase < 180 THEN recency_category = 'Lapsed';
        ELSE recency_category = 'Inactive';
    END;
    
RUN;

/* Step 2.2: Merge products with transaction details */
DATA product_transactions;
    MERGE raw_products (IN=in_prod)
          raw_transactions (IN=in_trans);
    BY product_key;
    
    /* Product performance metrics */
    IF in_prod AND in_trans THEN DO;
        /* Sales metrics */
        units_sold = quantity_ordered;
        revenue_generated = subtotal_amount;
        profit_generated = units_sold * profit_per_unit;
        
        /* Discount impact */
        discount_given = discount_amount;
        revenue_loss_from_discount = discount_given;
        effective_margin = ((revenue_generated - discount_given - (units_sold * unit_cost)) / revenue_generated) * 100;
        
        /* Inventory impact */
        stock_reduction = units_sold;
        new_stock_level = stock_level - stock_reduction;
        stock_turnover_contribution = units_sold;
    END;
    
RUN;

/* Step 2.3: Create comprehensive transaction view */
DATA transaction_details;
    MERGE customer_transactions (IN=in_ct)
          product_transactions (IN=in_pt);
    BY transaction_key;
    
    IF in_ct AND in_pt THEN DO;
        /* Complete transaction record */
        complete_record = 1;
        
        /* Customer value metrics */
        customer_revenue = revenue_amount;
        customer_profit = profit_generated;
        
        /* Product performance */
        product_revenue = revenue_generated;
        product_profit = profit_generated;
        
        /* Combined metrics */
        total_transaction_value = transaction_total;
        total_transaction_profit = profit_generated;
        transaction_margin = (total_transaction_profit / total_transaction_value) * 100;
    END;
    ELSE DO;
        complete_record = 0;
    END;
    
RUN;

/* -------------------------------------------------------------------------- */
/* SECTION 3: AGGREGATIONS AND SUMMARY STATISTICS                            */
/* -------------------------------------------------------------------------- */

/* Step 3.1: Customer summary statistics */
DATA customer_summary;
    SET customer_transactions;
    BY customer_key;
    
    /* Initialize accumulators */
    RETAIN total_purchases 0;
    RETAIN total_revenue 0;
    RETAIN total_quantity 0;
    RETAIN first_purchase_date;
    RETAIN last_purchase_date;
    
    /* Accumulate metrics */
    IF FIRST.customer_key THEN DO;
        total_purchases = 0;
        total_revenue = 0;
        total_quantity = 0;
        first_purchase_date = .;
        last_purchase_date = .;
    END;
    
    total_purchases + 1;
    total_revenue + revenue_amount;
    total_quantity + quantity_ordered;
    
    IF first_purchase_date = . THEN first_purchase_date = transaction_date;
    last_purchase_date = transaction_date;
    
    /* Calculate summaries at last record */
    IF LAST.customer_key THEN DO;
        /* Purchase frequency */
        purchase_count = total_purchases;
        
        /* Revenue metrics */
        customer_lifetime_value = total_revenue;
        average_order_value = total_revenue / total_purchases;
        total_items_purchased = total_quantity;
        average_items_per_order = total_quantity / total_purchases;
        
        /* Time-based metrics */
        customer_lifetime_days = INTCK('DAY', first_purchase_date, last_purchase_date);
        customer_lifetime_months = INTCK('MONTH', first_purchase_date, last_purchase_date);
        
        /* Purchase frequency rate */
        IF customer_lifetime_days > 0 THEN DO;
            purchases_per_month = (total_purchases / customer_lifetime_days) * 30;
            revenue_per_day = total_revenue / customer_lifetime_days;
        END;
        ELSE DO;
            purchases_per_month = 0;
            revenue_per_day = 0;
        END;
        
        /* Customer segmentation metrics */
        recency_score = days_since_last_purchase;
        frequency_score = purchase_count;
        monetary_score = customer_lifetime_value;
        
        /* RFM scoring */
        IF recency_score < 30 THEN recency_rating = 5;
        ELSE IF recency_score < 60 THEN recency_rating = 4;
        ELSE IF recency_score < 90 THEN recency_rating = 3;
        ELSE IF recency_score < 180 THEN recency_rating = 2;
        ELSE recency_rating = 1;
        
        IF frequency_score >= 20 THEN frequency_rating = 5;
        ELSE IF frequency_score >= 10 THEN frequency_rating = 4;
        ELSE IF frequency_score >= 5 THEN frequency_rating = 3;
        ELSE IF frequency_score >= 2 THEN frequency_rating = 2;
        ELSE frequency_rating = 1;
        
        IF monetary_score >= 1000 THEN monetary_rating = 5;
        ELSE IF monetary_score >= 500 THEN monetary_rating = 4;
        ELSE IF monetary_score >= 250 THEN monetary_rating = 3;
        ELSE IF monetary_score >= 100 THEN monetary_rating = 2;
        ELSE monetary_rating = 1;
        
        /* Combined RFM score */
        rfm_score = (recency_rating * 100) + (frequency_rating * 10) + monetary_rating;
        
        /* Customer segment assignment */
        customer_segment = '';
        IF rfm_score >= 444 THEN customer_segment = 'Champions';
        ELSE IF rfm_score >= 344 THEN customer_segment = 'Loyal Customers';
        ELSE IF rfm_score >= 334 THEN customer_segment = 'Potential Loyalists';
        ELSE IF rfm_score >= 313 THEN customer_segment = 'Recent Customers';
        ELSE IF rfm_score >= 233 THEN customer_segment = 'Promising';
        ELSE IF rfm_score >= 133 THEN customer_segment = 'Customers Needing Attention';
        ELSE IF rfm_score >= 123 THEN customer_segment = 'About to Sleep';
        ELSE IF rfm_score >= 113 THEN customer_segment = 'At Risk';
        ELSE IF rfm_score >= 213 THEN customer_segment = 'Cannot Lose Them';
        ELSE customer_segment = 'Lost';
        
        OUTPUT;
    END;
    
RUN;

/* Step 3.2: Product performance summary */
DATA product_summary;
    SET product_transactions;
    BY product_key;
    
    /* Initialize accumulators */
    RETAIN total_units_sold 0;
    RETAIN total_revenue 0;
    RETAIN total_profit 0;
    RETAIN total_transactions 0;
    RETAIN total_discount_given 0;
    
    /* Accumulate metrics */
    IF FIRST.product_key THEN DO;
        total_units_sold = 0;
        total_revenue = 0;
        total_profit = 0;
        total_transactions = 0;
        total_discount_given = 0;
    END;
    
    total_units_sold + units_sold;
    total_revenue + revenue_generated;
    total_profit + profit_generated;
    total_transactions + 1;
    total_discount_given + discount_given;
    
    /* Calculate summaries at last record */
    IF LAST.product_key THEN DO;
        /* Sales performance */
        total_sales_volume = total_units_sold;
        total_sales_revenue = total_revenue;
        total_sales_profit = total_profit;
        transaction_count = total_transactions;
        
        /* Average metrics */
        average_units_per_transaction = total_units_sold / transaction_count;
        average_revenue_per_transaction = total_revenue / transaction_count;
        average_profit_per_transaction = total_profit / transaction_count;
        
        /* Profitability metrics */
        total_product_margin = (total_profit / total_revenue) * 100;
        profit_per_unit_sold = total_profit / total_units_sold;
        
        /* Discount analysis */
        total_discounts = total_discount_given;
        average_discount_per_transaction = total_discounts / transaction_count;
        discount_rate_average = (total_discounts / (total_revenue + total_discounts)) * 100;
        
        /* Performance ratings */
        IF total_sales_revenue >= 10000 THEN revenue_rating = 'High';
        ELSE IF total_sales_revenue >= 5000 THEN revenue_rating = 'Medium';
        ELSE revenue_rating = 'Low';
        
        IF total_product_margin >= 40 THEN margin_rating = 'High';
        ELSE IF total_product_margin >= 25 THEN margin_rating = 'Medium';
        ELSE margin_rating = 'Low';
        
        /* Product lifecycle classification */
        IF total_sales_volume >= 1000 THEN lifecycle_stage = 'Maturity';
        ELSE IF total_sales_volume >= 100 THEN lifecycle_stage = 'Growth';
        ELSE lifecycle_stage = 'Introduction';
        
        OUTPUT;
    END;
    
RUN;

/* Step 3.3: Time-based sales analysis */
DATA daily_sales_summary;
    SET transaction_details;
    BY transaction_date;
    
    /* Initialize daily accumulators */
    RETAIN daily_transactions 0;
    RETAIN daily_revenue 0;
    RETAIN daily_profit 0;
    RETAIN daily_units 0;
    RETAIN daily_customers 0;
    
    /* Accumulate daily metrics */
    IF FIRST.transaction_date THEN DO;
        daily_transactions = 0;
        daily_revenue = 0;
        daily_profit = 0;
        daily_units = 0;
        daily_customers = 0;
    END;
    
    daily_transactions + 1;
    daily_revenue + total_transaction_value;
    daily_profit + total_transaction_profit;
    daily_units + quantity_ordered;
    daily_customers + 1;
    
    /* Calculate daily summaries */
    IF LAST.transaction_date THEN DO;
        /* Daily totals */
        transactions_per_day = daily_transactions;
        revenue_per_day_total = daily_revenue;
        profit_per_day_total = daily_profit;
        units_sold_per_day = daily_units;
        unique_customers_per_day = daily_customers;
        
        /* Daily averages */
        average_transaction_value = daily_revenue / daily_transactions;
        average_profit_per_transaction = daily_profit / daily_transactions;
        average_units_per_transaction = daily_units / daily_transactions;
        
        /* Daily margin */
        daily_margin_percentage = (daily_profit / daily_revenue) * 100;
        
        /* Day classification */
        IF revenue_per_day_total >= 10000 THEN day_performance = 'Excellent';
        ELSE IF revenue_per_day_total >= 5000 THEN day_performance = 'Good';
        ELSE IF revenue_per_day_total >= 2000 THEN day_performance = 'Average';
        ELSE day_performance = 'Below Average';
        
        OUTPUT;
    END;
    
RUN;

/* -------------------------------------------------------------------------- */
/* SECTION 4: ADVANCED CALCULATIONS AND DERIVED METRICS                      */
/* -------------------------------------------------------------------------- */

/* Step 4.1: Customer cohort analysis */
DATA customer_cohorts;
    SET customer_summary;
    
    /* Cohort assignment based on first purchase */
    first_purchase_year = YEAR(first_purchase_date);
    first_purchase_month = MONTH(first_purchase_date);
    first_purchase_quarter = QTR(first_purchase_date);
    
    cohort_label = PUT(first_purchase_year, 4.) || '-' || PUT(first_purchase_quarter, 1.) || 'Q';
    cohort_month = PUT(first_purchase_year, 4.) || '-' || PUT(first_purchase_month, Z2.);
    
    /* Time since first purchase */
    months_since_first_purchase = INTCK('MONTH', first_purchase_date, TODAY());
    quarters_since_first_purchase = INTCK('QTR', first_purchase_date, TODAY());
    
    /* Cohort performance metrics */
    cohort_value = customer_lifetime_value;
    cohort_frequency = purchase_count;
    
    /* Retention indicators */
    is_retained = (recency_rating >= 3);
    is_active_in_cohort = (days_since_last_purchase <= 90);
    
    /* Cohort maturity */
    IF months_since_first_purchase < 3 THEN cohort_maturity = 'New';
    ELSE IF months_since_first_purchase < 12 THEN cohort_maturity = 'Developing';
    ELSE IF months_since_first_purchase < 24 THEN cohort_maturity = 'Established';
    ELSE cohort_maturity = 'Mature';
    
RUN;

/* Step 4.2: Product category performance */
DATA category_performance;
    SET product_summary;
    
    /* Category-level aggregations */
    category_revenue = total_sales_revenue;
    category_profit = total_sales_profit;
    category_volume = total_sales_volume;
    
    /* Category metrics */
    category_margin = (category_profit / category_revenue) * 100;
    category_profit_per_unit = category_profit / category_volume;
    
    /* Market share proxy */
    category_transaction_share = transaction_count;
    
    /* Performance indicators */
    is_top_revenue_category = (category_revenue >= 50000);
    is_top_profit_category = (category_profit >= 20000);
    is_high_volume_category = (category_volume >= 5000);
    
    /* Strategic classification */
    strategic_category = '';
    IF is_top_revenue_category AND is_top_profit_category THEN strategic_category = 'Star';
    ELSE IF is_top_revenue_category THEN strategic_category = 'Cash Cow';
    ELSE IF is_high_volume_category THEN strategic_category = 'Question Mark';
    ELSE strategic_category = 'Dog';
    
    /* Growth potential */
    IF lifecycle_stage = 'Introduction' AND total_product_margin > 30 THEN 
        growth_potential = 'High';
    ELSE IF lifecycle_stage = 'Growth' THEN 
        growth_potential = 'Medium';
    ELSE 
        growth_potential = 'Low';
    
RUN;

/* Step 4.3: Customer lifetime value projections */
DATA customer_ltv_projection;
    SET customer_summary;
    
    /* Historical metrics */
    historical_clv = customer_lifetime_value;
    historical_avg_order = average_order_value;
    historical_frequency = purchases_per_month;
    
    /* Retention probability based on RFM */
    retention_probability = rfm_score / 555;
    
    /* Projected future purchases (12 month projection) */
    projected_monthly_purchases = historical_frequency * retention_probability;
    projected_annual_purchases = projected_monthly_purchases * 12;
    
    /* Projected revenue */
    projected_annual_revenue = projected_annual_purchases * historical_avg_order;
    
    /* Discount factor for present value */
    discount_rate = 0.10;
    discount_factor = 1 / (1 + discount_rate);
    
    /* Present value of future revenue */
    pv_year1 = projected_annual_revenue * discount_factor;
    pv_year2 = projected_annual_revenue * (discount_factor ** 2);
    pv_year3 = projected_annual_revenue * (discount_factor ** 3);
    
    /* Total projected CLV */
    projected_clv_3year = pv_year1 + pv_year2 + pv_year3;
    total_clv = historical_clv + projected_clv_3year;
    
    /* Customer value classification */
    IF total_clv >= 5000 THEN value_tier = 'Platinum';
    ELSE IF total_clv >= 2000 THEN value_tier = 'Gold';
    ELSE IF total_clv >= 500 THEN value_tier = 'Silver';
    ELSE value_tier = 'Bronze';
    
    /* Investment recommendation */
    max_acquisition_cost = total_clv * 0.20;
    max_retention_spend = projected_clv_3year * 0.15;
    
RUN;

/* Step 4.4: Product pricing optimization */
DATA product_pricing_analysis;
    SET product_summary;
    
    /* Current pricing metrics */
    current_price = base_price;
    current_cost = unit_cost;
    current_margin = profit_margin;
    
    /* Price elasticity proxy */
    units_at_current_price = total_sales_volume;
    revenue_at_current_price = total_sales_revenue;
    
    /* Scenario 1: 10% price increase */
    price_scenario1 = current_price * 1.10;
    estimated_volume_scenario1 = units_at_current_price * 0.90;
    revenue_scenario1 = price_scenario1 * estimated_volume_scenario1;
    profit_scenario1 = (price_scenario1 - current_cost) * estimated_volume_scenario1;
    margin_scenario1 = ((price_scenario1 - current_cost) / price_scenario1) * 100;
    
    /* Scenario 2: 5% price increase */
    price_scenario2 = current_price * 1.05;
    estimated_volume_scenario2 = units_at_current_price * 0.95;
    revenue_scenario2 = price_scenario2 * estimated_volume_scenario2;
    profit_scenario2 = (price_scenario2 - current_cost) * estimated_volume_scenario2;
    margin_scenario2 = ((price_scenario2 - current_cost) / price_scenario2) * 100;
    
    /* Scenario 3: 5% price decrease */
    price_scenario3 = current_price * 0.95;
    estimated_volume_scenario3 = units_at_current_price * 1.10;
    revenue_scenario3 = price_scenario3 * estimated_volume_scenario3;
    profit_scenario3 = (price_scenario3 - current_cost) * estimated_volume_scenario3;
    margin_scenario3 = ((price_scenario3 - current_cost) / price_scenario3) * 100;
    
    /* Scenario 4: 10% price decrease */
    price_scenario4 = current_price * 0.90;
    estimated_volume_scenario4 = units_at_current_price * 1.20;
    revenue_scenario4 = price_scenario4 * estimated_volume_scenario4;
    profit_scenario4 = (price_scenario4 - current_cost) * estimated_volume_scenario4;
    margin_scenario4 = ((price_scenario4 - current_cost) / price_scenario4) * 100;
    
    /* Compare scenarios */
    current_profit = total_sales_profit;
    
    profit_change_scenario1 = profit_scenario1 - current_profit;
    profit_change_scenario2 = profit_scenario2 - current_profit;
    profit_change_scenario3 = profit_scenario3 - current_profit;
    profit_change_scenario4 = profit_scenario4 - current_profit;
    
    /* Optimal scenario identification */
    best_profit = MAX(current_profit, profit_scenario1, profit_scenario2, 
                      profit_scenario3, profit_scenario4);
    
    optimal_scenario = '';
    IF best_profit = profit_scenario1 THEN optimal_scenario = 'Increase 10%';
    ELSE IF best_profit = profit_scenario2 THEN optimal_scenario = 'Increase 5%';
    ELSE IF best_profit = profit_scenario3 THEN optimal_scenario = 'Decrease 5%';
    ELSE IF best_profit = profit_scenario4 THEN optimal_scenario = 'Decrease 10%';
    ELSE optimal_scenario = 'Keep Current';
    
RUN;

/* -------------------------------------------------------------------------- */
/* SECTION 5: SEASONAL AND TREND ANALYSIS                                    */
/* -------------------------------------------------------------------------- */

/* Step 5.1: Monthly trend analysis */
DATA monthly_trends;
    SET daily_sales_summary;
    BY transaction_year transaction_month;
    
    /* Initialize monthly accumulators */
    RETAIN monthly_revenue 0;
    RETAIN monthly_profit 0;
    RETAIN monthly_transactions 0;
    RETAIN monthly_units 0;
    
    IF FIRST.transaction_month THEN DO;
        monthly_revenue = 0;
        monthly_profit = 0;
        monthly_transactions = 0;
        monthly_units = 0;
    END;
    
    monthly_revenue + revenue_per_day_total;
    monthly_profit + profit_per_day_total;
    monthly_transactions + transactions_per_day;
    monthly_units + units_sold_per_day;
    
    IF LAST.transaction_month THEN DO;
        /* Monthly totals */
        total_monthly_revenue = monthly_revenue;
        total_monthly_profit = monthly_profit;
        total_monthly_transactions = monthly_transactions;
        total_monthly_units = monthly_units;
        
        /* Monthly averages */
        avg_daily_revenue = monthly_revenue / DAY(INTNX('MONTH', transaction_date, 0, 'E'));
        avg_daily_transactions = monthly_transactions / DAY(INTNX('MONTH', transaction_date, 0, 'E'));
        
        /* Monthly metrics */
        monthly_margin = (monthly_profit / monthly_revenue) * 100;
        avg_transaction_value_monthly = monthly_revenue / monthly_transactions;
        
        /* Month identification */
        month_name = '';
        IF transaction_month = 1 THEN month_name = 'January';
        ELSE IF transaction_month = 2 THEN month_name = 'February';
        ELSE IF transaction_month = 3 THEN month_name = 'March';
        ELSE IF transaction_month = 4 THEN month_name = 'April';
        ELSE IF transaction_month = 5 THEN month_name = 'May';
        ELSE IF transaction_month = 6 THEN month_name = 'June';
        ELSE IF transaction_month = 7 THEN month_name = 'July';
        ELSE IF transaction_month = 8 THEN month_name = 'August';
        ELSE IF transaction_month = 9 THEN month_name = 'September';
        ELSE IF transaction_month = 10 THEN month_name = 'October';
        ELSE IF transaction_month = 11 THEN month_name = 'November';
        ELSE month_name = 'December';
        
        /* Season assignment */
        season = '';
        IF transaction_month IN (12, 1, 2) THEN season = 'Winter';
        ELSE IF transaction_month IN (3, 4, 5) THEN season = 'Spring';
        ELSE IF transaction_month IN (6, 7, 8) THEN season = 'Summer';
        ELSE season = 'Fall';
        
        OUTPUT;
    END;
    
RUN;

/* Step 5.2: Quarterly performance analysis */
DATA quarterly_analysis;
    SET monthly_trends;
    BY transaction_year transaction_quarter;
    
    /* Initialize quarterly accumulators */
    RETAIN quarterly_revenue 0;
    RETAIN quarterly_profit 0;
    RETAIN quarterly_transactions 0;
    
    IF FIRST.transaction_quarter THEN DO;
        quarterly_revenue = 0;
        quarterly_profit = 0;
        quarterly_transactions = 0;
    END;
    
    quarterly_revenue + total_monthly_revenue;
    quarterly_profit + total_monthly_profit;
    quarterly_transactions + total_monthly_transactions;
    
    IF LAST.transaction_quarter THEN DO;
        /* Quarterly totals */
        q_revenue = quarterly_revenue;
        q_profit = quarterly_profit;
        q_transactions = quarterly_transactions;
        
        /* Quarterly metrics */
        q_margin = (q_profit / q_revenue) * 100;
        q_avg_transaction = q_revenue / q_transactions;
        
        /* Quarter label */
        quarter_label = PUT(transaction_year, 4.) || '-Q' || PUT(transaction_quarter, 1.);
        
        /* Quarter performance rating */
        IF q_revenue >= 100000 THEN quarter_rating = 'Excellent';
        ELSE IF q_revenue >= 75000 THEN quarter_rating = 'Good';
        ELSE IF q_revenue >= 50000 THEN quarter_rating = 'Average';
        ELSE quarter_rating = 'Below Target';
        
        OUTPUT;
    END;
    
RUN;

/* Step 5.3: Year-over-year comparison */
DATA yoy_comparison;
    SET quarterly_analysis;
    
    /* Lag previous year metrics */
    lag_year = LAG4(transaction_year);
    lag_quarter = LAG4(transaction_quarter);
    lag_revenue = LAG4(q_revenue);
    lag_profit = LAG4(q_profit);
    lag_transactions = LAG4(q_transactions);
    
    /* Year-over-year calculations */
    IF transaction_year = lag_year + 1 AND transaction_quarter = lag_quarter THEN DO;
        yoy_revenue_growth = ((q_revenue - lag_revenue) / lag_revenue) * 100;
        yoy_profit_growth = ((q_profit - lag_profit) / lag_profit) * 100;
        yoy_transaction_growth = ((q_transactions - lag_transactions) / lag_transactions) * 100;
        
        /* Growth classification */
        IF yoy_revenue_growth >= 20 THEN growth_rate = 'High Growth';
        ELSE IF yoy_revenue_growth >= 10 THEN growth_rate = 'Moderate Growth';
        ELSE IF yoy_revenue_growth >= 0 THEN growth_rate = 'Low Growth';
        ELSE growth_rate = 'Decline';
    END;
    
RUN;

/* Step 5.4: Seasonality index calculation */
DATA seasonality_index;
    SET monthly_trends;
    
    /* Calculate average monthly revenue */
    RETAIN annual_revenue 0;
    RETAIN month_count 0;
    
    annual_revenue + total_monthly_revenue;
    month_count + 1;
    
    /* Calculate seasonality at end */
    avg_monthly_revenue = annual_revenue / month_count;
    
    /* Seasonality index */
    seasonality_factor = total_monthly_revenue / avg_monthly_revenue;
    
    /* Seasonal strength */
    IF seasonality_factor >= 1.2 THEN seasonal_strength = 'Strong Peak';
    ELSE IF seasonality_factor >= 1.1 THEN seasonal_strength = 'Peak';
    ELSE IF seasonality_factor >= 0.9 THEN seasonal_strength = 'Normal';
    ELSE IF seasonality_factor >= 0.8 THEN seasonal_strength = 'Trough';
    ELSE seasonal_strength = 'Strong Trough';
    
RUN;

/* -------------------------------------------------------------------------- */
/* SECTION 6: CUSTOMER SEGMENTATION AND TARGETING                            */
/* -------------------------------------------------------------------------- */

/* Step 6.1: Demographic segmentation */
DATA demographic_segments;
    SET customer_summary;
    
    /* Age-based segments */
    age_segment = '';
    IF current_age < 25 THEN age_segment = 'Gen Z';
    ELSE IF current_age < 40 THEN age_segment = 'Millennials';
    ELSE IF current_age < 56 THEN age_segment = 'Gen X';
    ELSE IF current_age < 75 THEN age_segment = 'Baby Boomers';
    ELSE age_segment = 'Silent Generation';
    
    /* Combine with value tier */
    demographic_value_segment = TRIM(age_segment) || ' - ' || TRIM(value_tier);
    
    /* Lifestyle indicators */
    is_digital_native = (current_age < 40);
    prefers_online = (is_digital_native AND is_online);
    
    /* Purchase behavior by demographics */
    avg_basket_size = average_order_value;
    purchase_frequency_segment = '';
    IF purchases_per_month >= 4 THEN purchase_frequency_segment = 'Very Frequent';
    ELSE IF purchases_per_month >= 2 THEN purchase_frequency_segment = 'Frequent';
    ELSE IF purchases_per_month >= 1 THEN purchase_frequency_segment = 'Regular';
    ELSE purchase_frequency_segment = 'Occasional';
    
RUN;

/* Step 6.2: Behavioral segmentation */
DATA behavioral_segments;
    SET customer_summary;
    
    /* Purchase recency segmentation */
    recency_segment = '';
    IF days_since_last_purchase <= 30 THEN recency_segment = 'Active Buyer';
    ELSE IF days_since_last_purchase <= 60 THEN recency_segment = 'Recent Buyer';
    ELSE IF days_since_last_purchase <= 90 THEN recency_segment = 'Lapsing Buyer';
    ELSE IF days_since_last_purchase <= 180 THEN recency_segment = 'Lapsed Buyer';
    ELSE recency_segment = 'Lost Buyer';
    
    /* Purchase frequency segmentation */
    frequency_segment = '';
    IF purchase_count >= 50 THEN frequency_segment = 'Super Loyal';
    ELSE IF purchase_count >= 20 THEN frequency_segment = 'Loyal';
    ELSE IF purchase_count >= 10 THEN frequency_segment = 'Regular';
    ELSE IF purchase_count >= 5 THEN frequency_segment = 'Occasional';
    ELSE frequency_segment = 'One-Time';
    
    /* Monetary segmentation */
    monetary_segment = '';
    IF customer_lifetime_value >= 5000 THEN monetary_segment = 'High Spender';
    ELSE IF customer_lifetime_value >= 2000 THEN monetary_segment = 'Medium Spender';
    ELSE IF customer_lifetime_value >= 500 THEN monetary_segment = 'Low Spender';
    ELSE monetary_segment = 'Minimal Spender';
    
    /* Combined behavioral segment */
    behavioral_profile = TRIM(recency_segment) || ' / ' || TRIM(frequency_segment) || ' / ' || TRIM(monetary_segment);
    
RUN;

/* Step 6.3: Predictive segments */
DATA predictive_segments;
    SET customer_ltv_projection;
    
    /* Churn risk assessment */
    churn_risk_score = 100 - (retention_probability * 100);
    
    churn_risk_level = '';
    IF churn_risk_score >= 70 THEN churn_risk_level = 'Very High';
    ELSE IF churn_risk_score >= 50 THEN churn_risk_level = 'High';
    ELSE IF churn_risk_score >= 30 THEN churn_risk_level = 'Medium';
    ELSE churn_risk_level = 'Low';
    
    /* Growth potential */
    growth_potential_score = (projected_clv_3year / historical_clv) * 100;
    
    growth_potential_level = '';
    IF growth_potential_score >= 150 THEN growth_potential_level = 'Very High';
    ELSE IF growth_potential_score >= 100 THEN growth_potential_level = 'High';
    ELSE IF growth_potential_score >= 50 THEN growth_potential_level = 'Medium';
    ELSE growth_potential_level = 'Low';
    
    /* Strategic segment */
    strategic_segment = '';
    IF churn_risk_level = 'Low' AND growth_potential_level IN ('High', 'Very High') THEN 
        strategic_segment = 'Invest for Growth';
    ELSE IF churn_risk_level = 'Low' AND value_tier IN ('Platinum', 'Gold') THEN 
        strategic_segment = 'Maintain and Nurture';
    ELSE IF churn_risk_level IN ('High', 'Very High') AND value_tier IN ('Platinum', 'Gold') THEN 
        strategic_segment = 'Save at All Costs';
    ELSE IF churn_risk_level IN ('High', 'Very High') THEN 
        strategic_segment = 'Consider Letting Go';
    ELSE 
        strategic_segment = 'Standard Treatment';
    
RUN;

/* -------------------------------------------------------------------------- */
/* SECTION 7: FINAL REPORTING AND EXECUTIVE DASHBOARDS                       */
/* -------------------------------------------------------------------------- */

/* Step 7.1: Executive summary metrics */
DATA executive_summary;
    SET transaction_details;
    
    /* Overall business metrics */
    RETAIN total_company_revenue 0;
    RETAIN total_company_profit 0;
    RETAIN total_company_transactions 0;
    RETAIN total_company_customers 0;
    RETAIN total_company_products 0;
    
    total_company_revenue + total_transaction_value;
    total_company_profit + total_transaction_profit;
    total_company_transactions + 1;
    
    /* Key performance indicators */
    company_margin = (total_company_profit / total_company_revenue) * 100;
    avg_transaction_size = total_company_revenue / total_company_transactions;
    avg_profit_per_transaction = total_company_profit / total_company_transactions;
    
    /* Health metrics */
    profit_per_dollar = total_company_profit / total_company_revenue;
    revenue_per_transaction = avg_transaction_size;
    
RUN;

/* Step 7.2: Top performers identification */
DATA top_performers;
    SET customer_summary;
    
    /* Rank customers by various metrics */
    rank_by_revenue = .;
    rank_by_frequency = .;
    rank_by_recency = .;
    
    /* Top customer flags */
    is_top_10_pct_revenue = (customer_lifetime_value >= 2000);
    is_top_10_pct_frequency = (purchase_count >= 20);
    is_vip_customer = (customer_segment IN ('Champions', 'Loyal Customers'));
    
    /* Performance tier */
    IF is_top_10_pct_revenue AND is_top_10_pct_frequency THEN 
        performance_tier = 'Elite';
    ELSE IF is_top_10_pct_revenue OR is_top_10_pct_frequency THEN 
        performance_tier = 'Premium';
    ELSE IF is_vip_customer THEN 
        performance_tier = 'Standard Plus';
    ELSE 
        performance_tier = 'Standard';
    
RUN;

/* Step 7.3: Risk and opportunity report */
DATA risk_opportunity;
    MERGE predictive_segments (IN=in_pred)
          behavioral_segments (IN=in_behav);
    BY customer_key;
    
    IF in_pred AND in_behav THEN DO;
        /* Risk indicators */
        at_risk_flag = (churn_risk_level IN ('High', 'Very High'));
        high_value_at_risk = (at_risk_flag AND value_tier IN ('Platinum', 'Gold'));
        
        /* Opportunity indicators */
        growth_opportunity = (growth_potential_level IN ('High', 'Very High'));
        upsell_opportunity = (value_tier IN ('Silver', 'Bronze') AND frequency_segment IN ('Loyal', 'Super Loyal'));
        cross_sell_opportunity = (purchase_count >= 10 AND average_items_per_order < 3);
        
        /* Action priority */
        action_priority = 0;
        IF high_value_at_risk THEN action_priority = 1;
        ELSE IF at_risk_flag THEN action_priority = 2;
        ELSE IF upsell_opportunity THEN action_priority = 3;
        ELSE IF cross_sell_opportunity THEN action_priority = 4;
        ELSE IF growth_opportunity THEN action_priority = 5;
        
        /* Recommended action */
        recommended_action = '';
        IF action_priority = 1 THEN recommended_action = 'Immediate Retention Intervention';
        ELSE IF action_priority = 2 THEN recommended_action = 'Retention Campaign';
        ELSE IF action_priority = 3 THEN recommended_action = 'Upsell Campaign';
        ELSE IF action_priority = 4 THEN recommended_action = 'Cross-Sell Campaign';
        ELSE IF action_priority = 5 THEN recommended_action = 'Growth Nurture';
        ELSE recommended_action = 'Maintain Current Strategy';
    END;
    
RUN;

/* Step 7.4: Final consolidated report */
DATA final_consolidated_report;
    MERGE executive_summary (IN=in_exec)
          top_performers (IN=in_top)
          risk_opportunity (IN=in_risk);
    BY customer_key;
    
    /* Consolidation flags */
    has_executive_data = in_exec;
    has_performance_data = in_top;
    has_risk_opportunity_data = in_risk;
    
    /* Complete record indicator */
    is_complete_record = (in_exec AND in_top AND in_risk);
    
    /* Final customer score */
    IF is_complete_record THEN DO;
        /* Weighted score calculation */
        revenue_weight = 0.40;
        frequency_weight = 0.30;
        recency_weight = 0.15;
        engagement_weight = 0.15;
        
        revenue_score = (customer_lifetime_value / 10000) * 100;
        frequency_score = (purchase_count / 50) * 100;
        recency_score = (30 / MAX(days_since_last_purchase, 1)) * 100;
        engagement_score = retention_probability * 100;
        
        /* Composite customer score */
        composite_score = (revenue_score * revenue_weight) +
                         (frequency_score * frequency_weight) +
                         (recency_score * recency_weight) +
                         (engagement_score * engagement_weight);
        
        /* Final rating */
        IF composite_score >= 80 THEN final_rating = 'A+';
        ELSE IF composite_score >= 70 THEN final_rating = 'A';
        ELSE IF composite_score >= 60 THEN final_rating = 'B+';
        ELSE IF composite_score >= 50 THEN final_rating = 'B';
        ELSE IF composite_score >= 40 THEN final_rating = 'C+';
        ELSE IF composite_score >= 30 THEN final_rating = 'C';
        ELSE final_rating = 'D';
    END;
    ELSE DO;
        composite_score = .;
        final_rating = 'Incomplete Data';
    END;
    
RUN;

/* -------------------------------------------------------------------------- */
/* END OF COMPREHENSIVE TEST PROGRAM                                          */
/* -------------------------------------------------------------------------- */
