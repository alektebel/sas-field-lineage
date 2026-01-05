/* Example SAS Code - Sales Analysis */

DATA raw_sales;
    SET input_data;
    revenue = quantity * price;
    discount_amount = revenue * discount_rate;
RUN;

DATA final_sales;
    SET raw_sales;
    net_revenue = revenue - discount_amount;
    profit = net_revenue - cost;
    profit_margin = profit / net_revenue;
RUN;

DATA summary;
    SET final_sales;
    total_profit = SUM(profit);
    avg_margin = MEAN(profit_margin);
RUN;
