# Installing an add-on

All add-ons follow the same pattern. Add-on-specific details (credentials, endpoints, defaults) are on each add-on's page.

## Where to install

| Splunk role | Install? | Why |
|---|---|---|
| Search heads | Yes | Search-time field extraction, aliases, CIM tags |
| Heavy forwarder, or the instance running the inputs | Yes | Runs the modular input and stores checkpoints in the KV Store |
| Indexers | Not needed | Events are already timestamped and line-broken by the input |
| Universal forwarders | No | UFs can't run the Python modular inputs |

**Splunk Cloud:** install from Splunkbase (or via Splunk support) on the search head; configure inputs on the Inputs Data Manager (IDM) or the search head, depending on your stack.

**Search head cluster:** install through the deployer. Configure inputs on one heavy forwarder rather than on the cluster, so each input runs once.

## Setup steps

1. **Install** the package (*Apps > Manage Apps > Install app from file*, or from Splunkbase) and restart if prompted.
2. **Create an index** for the data if you don't want to use `default`.
3. Open the add-on and go to **Configuration > Accounts > Add**. Enter the API details. Secrets are stored encrypted in Splunk's credential store, and the add-on tests them against the API before saving: if saving fails, the error message says why.
4. Optional: **Configuration > Proxy** (HTTP or SOCKS5, with optional credentials) and **Configuration > Logging** (set DEBUG while troubleshooting).
5. **Inputs > Create New Input:** choose the account, interval and index, plus any input-specific options.
6. Check data is arriving:
   ```
   index=<your_index> sourcetype=<the add-on's sourcetype> earliest=-1h
   ```

## Python versions

| Add-on | `python.required` | Splunk versions |
|---|---|---|
| Cortex Audit Logs | `3.13` | 10.2+ |
| All others | `3.9, 3.13` | 9.0+ (Splunk 10.2+ runs them on 3.13) |

## Upgrading from an older version

Install the new package over the old one (*Upgrade app* checkbox, or from Splunkbase). Version 1.1.0 of the VeeOne, NetApp and Prisma add-ons moved credentials from inputs to accounts: after upgrading, add an account, delete the old input and create a new one. Each add-on page has an *Upgrading* section with details.
