/* Complex SAS Example - Employee Salary Analysis */
/* This example demonstrates various SAS constructs and field lineage */

/* Step 1: Load and clean employee data */
DATA employees_clean;
    SET raw_employees;
    
    /* Clean names */
    full_name = TRIM(first_name) || ' ' || TRIM(last_name);
    
    /* Calculate tenure */
    years_employed = (TODAY() - hire_date) / 365.25;
    
    /* Standardize salary to annual */
    annual_salary = salary * 12;
RUN;

/* Step 2: Calculate department statistics */
DATA dept_stats;
    SET employees_clean;
    BY department;
    
    /* Running totals */
    dept_total_salary = SUM(annual_salary);
    dept_employee_count = COUNT(employee_id);
    
    /* Average calculations */
    dept_avg_salary = dept_total_salary / dept_employee_count;
    dept_avg_tenure = MEAN(years_employed);
RUN;

/* Step 3: Add performance bonus calculations */
DATA employee_compensation;
    MERGE employees_clean performance_ratings;
    BY employee_id;
    
    /* Calculate bonus based on performance */
    performance_multiplier = rating / 5.0;
    bonus_amount = annual_salary * 0.1 * performance_multiplier;
    
    /* Total compensation */
    total_compensation = annual_salary + bonus_amount;
    
    /* Bonus percentage */
    bonus_pct = (bonus_amount / annual_salary) * 100;
RUN;

/* Step 4: Final report with comparisons */
DATA final_report;
    MERGE employee_compensation dept_stats;
    BY department employee_id;
    
    /* Compare to department average */
    salary_vs_dept = annual_salary - dept_avg_salary;
    salary_vs_dept_pct = (salary_vs_dept / dept_avg_salary) * 100;
    
    /* Compensation rank indicators */
    above_dept_avg = (salary_vs_dept > 0);
    
    /* Tenure-based adjustments */
    tenure_bonus = years_employed * 1000;
    adjusted_compensation = total_compensation + tenure_bonus;
RUN;

/* Step 5: Summary statistics */
DATA summary_report;
    SET final_report;
    
    /* Company-wide statistics */
    company_total_compensation = SUM(adjusted_compensation);
    company_avg_bonus = MEAN(bonus_amount);
    company_avg_tenure = MEAN(years_employed);
    
    /* High performer identification */
    high_performer = (bonus_pct > 15);
    
    /* Cost calculations */
    cost_per_employee = adjusted_compensation;
    annual_cost_increase = cost_per_employee * 0.03;
RUN;
