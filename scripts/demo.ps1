$ErrorActionPreference = 'Stop'
$api = 'http://localhost:8000/api/v1'
$output = Join-Path $PSScriptRoot '..\demo-output'
New-Item -ItemType Directory -Force -Path $output | Out-Null

$health = Invoke-RestMethod "$api/health"
if ($health.status -ne 'ok') { throw 'Planner API is not healthy.' }
$demo = Invoke-RestMethod "$api/scenarios/demo-inputs"
if (-not $demo.synthetic) { throw 'Expected the labelled synthetic demo fixture.' }

$group = [guid]::NewGuid().ToString()
$common = @{
    group_id = $group; input_data_status = 'synthetic_demo'
    facility_type = 'collection_centre'; demand_by_ward = $demo.demand_by_ward
    fixed_costs = $demo.fixed_costs; capacities = $demo.capacities
    budget = 400000; max_facilities = 2; transport_cost_per_tonne_km = 1.4
    unserved_penalty_per_tonne = 1000000
    constraint_types = @('synthetic_waterbody', 'synthetic_sensitive_use')
}
$baselinePayload = $common.Clone()
$baselinePayload.scenario_type = 'baseline'; $baselinePayload.label = 'Demo baseline'
$baselinePayload.max_facilities = 1; $baselinePayload.baseline_facility_ids = @('SYN-C01')
$null = Invoke-RestMethod "$api/scenarios/run" -Method Post -ContentType 'application/json' -Body ($baselinePayload | ConvertTo-Json -Depth 20)

$scenario = $common.Clone()
$scenario.scenario_type = 'optimized'; $scenario.label = 'Seeded demo optimized'
$run = Invoke-RestMethod "$api/scenarios/run" -Method Post -ContentType 'application/json' -Body ($scenario | ConvertTo-Json -Depth 20)
$futurePayload = $common.Clone()
$futurePayload.scenario_type = 'future_demand'; $futurePayload.label = 'Demo future +25%'
$futurePayload.future_growth_percent = 25
$null = Invoke-RestMethod "$api/scenarios/run" -Method Post -ContentType 'application/json' -Body ($futurePayload | ConvertTo-Json -Depth 20)
Invoke-WebRequest "$api/reports/$($run.run_id).pdf" -OutFile (Join-Path $output 'scenario-report.pdf')
Invoke-WebRequest "$api/reports/$($run.run_id).csv" -OutFile (Join-Path $output 'scenario-report.csv')

$designDefaults = Invoke-RestMethod "$api/facility-design/defaults"
$designPayload = $designDefaults.defaults
Invoke-WebRequest "$api/facility-design/layout.pdf" -Method Post -ContentType 'application/json' `
    -Body ($designPayload | ConvertTo-Json -Depth 10) -OutFile (Join-Path $output 'conceptual-facility-layout.pdf')

Write-Host "Scenario run $($run.run_id) saved against $($run.dataset_version) ($($run.results.scenario_input_data_status))."
Write-Host "Selected sites: $($run.results.selected_facilities.candidate_id -join ', ')"
Write-Host ("Demand {0:N1} t; allocated {1:N1} t; unserved {2:N1} t; coverage {3:N1}%." -f `
    $run.results.total_demand_tonnes, $run.results.allocated_tonnes, $run.results.unserved_tonnes, $run.results.service_coverage_percent)
Write-Host "PDF, CSV and conceptual layout exported to $((Resolve-Path $output).Path)"
Write-Host 'Open the Vite URL to review the map, scenario controls and facility designer.'
