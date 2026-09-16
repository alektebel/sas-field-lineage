/* A single ordered session. Repeated writes get distinct logical versions. */
data work.stage;
  set raw.orders;
run;

proc sort data=work.stage out=work.sorted;
  by order_id;
run;

data mart.sales mart.audit;
  set work.sorted;
  label = 'A literal; semicolon and /* comment markers */';
run;

data mart.sales;
  set mart.sales;
  reviewed = 1;
run;

/* Runtime-dependent names remain symbolic in this first milestone. */
data _null_;
  set control.run_config(obs=1);
  call symputx('period', period, 'G');
run;

data mart.sales_&period.;
  set mart.sales;
run;
