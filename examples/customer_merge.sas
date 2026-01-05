/* Example SAS Code - Customer Merge */

DATA customer_orders;
    MERGE customers orders;
    BY customer_id;
    total_amount = quantity * unit_price;
    final_amount = total_amount - discount;
RUN;

DATA customer_summary;
    SET customer_orders;
    revenue_per_customer = total_amount / customer_count;
    profit_ratio = final_amount / total_amount;
RUN;
