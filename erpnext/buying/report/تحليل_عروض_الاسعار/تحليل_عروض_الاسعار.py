# Copyright (c) 2013, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt




import frappe
from frappe import _
from frappe.utils import cint, flt

from erpnext.setup.utils import get_exchange_rate


def execute(filters=None):
	if not filters:
		return [], []

	columns = get_columns(filters)
	supplier_quotation_data = get_data(filters)

	data, chart_data = prepare_data(supplier_quotation_data, filters)
	message = get_message()

	return columns, data, message, chart_data


def get_data(filters):
	sq = frappe.qb.DocType("Supplier Quotation 2")
	sq_item = frappe.qb.DocType("Supplier Quotation Item 2")

	query = (
		frappe.qb.from_(sq_item)
		.from_(sq)
		.select(
			sq_item.trade_name,
			sq_item.scientific_name,
			sq_item.country_of_origin,
			sq_item.amount,
			sq_item.rate,
			sq_item.comments,
			sq_item.uom,
			sq_item.manufacture_company,
			sq_item.expiry_date,
			sq.supplier.as_("supplier_name"),
			sq.valid_till,
		)
		.where(
			(sq_item.trade_name == sq.name)
			& (sq_item.docstatus < 2)
			& (sq.company == filters.get("company"))
			& (sq.transaction_date.between(filters.get("from_date"), filters.get("to_date")))
		)
		.orderby(sq.transaction_date, sq_item.scientific_name)
	)

	if filters.get("scientific_name"):
		query = query.where(sq_item.scientific_name == filters.get("scientific_name"))

	if filters.get("supplier_quotation "):
		query = query.where(sq_item.trade_name.isin(filters.get("supplier_quotation ")))

	if filters.get("manufacture_company"):
		query = query.where(sq_item.manufacture_company == filters.get("manufacture_company"))

	if filters.get("supplier"):
		query = query.where(sq.supplier.isin(filters.get("supplier")))

	if not filters.get("include_expired"):
		query = query.where(sq.status != "Expired")

	supplier_quotation_data = query.run(as_dict=True)

	return supplier_quotation_data


def prepare_data(supplier_quotation_data, filters):
	out, groups, country_of_origin_list, suppliers, chart_data = [], [], [], [], []
	group_wise_map = defaultdict(list)
	supplier_country_of_origin_price_map = {}

	group_by_field = (
		"supplier_name" if filters.get("group_by") == "Group by Supplier" else "scientific_name"
	)
	company_currency = frappe.db.get_default("currency")
	float_precision = cint(frappe.db.get_default("float_precision")) or 2

	for data in supplier_quotation_data:
		group = data.get(group_by_field)  # get item or supplier value for this row

		supplier_currency = frappe.db.get_value(
			"Supplier", data.get("supplier_name"), "default_currency"
		)

		if supplier_currency:
			exchange_rate = get_exchange_rate(supplier_currency, company_currency)
		else:
			exchange_rate = 1

		row = {
			"scientific_name": ""
			if group_by_field == "scientific_name"
			else data.get("scientific_name"),  # leave blank if group by field
			"supplier_name": "" if group_by_field == "supplier_name" else data.get("supplier_name"),
			"quotation": data.get("trade_name"),
			"country_of_origin": data.get("country_of_origin"),
			"price": flt(data.get("amount") * exchange_rate, float_precision),
			"uom": data.get("uom"),
			"price_list_currency": data.get("price_list_currency"),
			
			
			
			"rate": flt(data.get("rate"), float_precision),
			"manufacture_company": data.get("manufacture_company"),
			
			"expiry_date": data.get("expiry_date"),
		}
		row["price_per_unit"] = flt(row["price"]) / (flt(data.get("country_of_origin")) or 1)

		# map for report view of form {'supplier1'/'item1':[{},{},...]}
		group_wise_map[group].append(row)

		# map for chart preparation of the form {'supplier1': {'country_of_origin': 'price'}}
		supplier = data.get("supplier_name")
		if filters.get("scientific_name"):
			if not supplier in supplier_country_of_origin_price_map:
				supplier_country_of_origin_price_map[supplier] = {}
			supplier_country_of_origin_price_map[supplier][row["country_of_origin"]] = row["price"]

		groups.append(group)
		suppliers.append(supplier)
		country_of_origin_list.append(data.get("country_of_origin"))

	groups = list(set(groups))
	suppliers = list(set(suppliers))
	country_of_origin_list = list(set(country_of_origin_list))

	highlight_min_price = group_by_field == "scientific_name" or filters.get("scientific_name")

	# final data format for report view
	for group in groups:
		group_entries = group_wise_map[group]  # all entries pertaining to item/supplier
		group_entries[0].update({group_by_field: group})  # Add item/supplier name in first group row

		if highlight_min_price:
			prices = [group_entry["price_per_unit"] for group_entry in group_entries]
			min_price = min(prices)

		for entry in group_entries:
			if highlight_min_price and entry["price_per_unit"] == min_price:
				entry["min"] = 1
			out.append(entry)

	if filters.get("scientific_name"):
		# render chart only for one item comparison
		chart_data = prepare_chart_data(suppliers, country_of_origin_list, supplier_country_of_origin_price_map)

	return out, chart_data


def prepare_chart_data(suppliers, country_of_origin_list, supplier_country_of_origin_price_map):
	data_points_map = {}
	country_of_origin_list.sort()

	# create country_of_origin wise values map of the form {'country_of_origin1':[value1, value2]}
	for supplier in suppliers:
		entry = supplier_country_of_origin_price_map[supplier]
		for country_of_origin in country_of_origin_list:
			if not country_of_origin in data_points_map:
				data_points_map[country_of_origin] = []
			if country_of_origin in entry:
				data_points_map[country_of_origin].append(entry[country_of_origin])
			else:
				data_points_map[country_of_origin].append(None)

	dataset = []
	
	for country_of_origin in country_of_origin_list:
		datapoints = {
			"name": currency_symbol + " (country_of_origin " + str(country_of_origin) + " )",
			"values": data_points_map[country_of_origin],
		}
		dataset.append(datapoints)

	chart_data = {"data": {"labels": suppliers, "datasets": dataset}, "type": "bar"}

	return chart_data


def get_columns(filters):
	currency = frappe.get_cached_value("Company", filters.get("company"), "default_currency")

	group_by_columns = [
		{
			"fieldname": "supplier_name",
			"label": _("Supplier"),
			"fieldtype": "Link",
			"options": "Supplier",
			"width": 150,
		},
		{
			"fieldname": "scientific_name",
			"label": _("Item"),
			"fieldtype": "Link",
			"options": "Item",
			"width": 150,
		},
	]

	columns = [
		{"fieldname": "uom", "label": _("UOM"), "fieldtype": "Link", "options": "UOM", "width": 90},
		{"fieldname": "country_of_origin", "label": _("Quantity"), "fieldtype": "Float", "width": 80},
		
		{
			"fieldname": "price",
			"label": _("Price"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 110,
		},
		
		{
			"fieldname": "price_per_unit",
			"label": _("Price per Unit (Stock UOM)"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 120,
		},
		{
			"fieldname": "base_amount",
			"label": _("Price ({0})").format(currency),
			"fieldtype": "Currency",
			"options": "price_list_currency",
			"width": 180,
		},
		{
			"fieldname": "rate",
			"label": _("Price Per Unit ({0})").format(currency),
			"fieldtype": "Currency",
			"options": "price_list_currency",
			"width": 180,
		},
		{
			"fieldname": "quotation",
			"label": _("Supplier Quotation"),
			"fieldtype": "Link",
			"options": "Supplier Quotation",
			"width": 200,
		},
		{"fieldname": "valid_till", "label": _("Valid Till"), "fieldtype": "Date", "width": 100},
		{
			"fieldname": "expiry_date",
			"label": _("Lead Time (Days)"),
			"fieldtype": "Int",
			"width": 100,
		},
		{
			"fieldname": "manufacture_company",
			"label": _("Request for Quotation"),
			"fieldtype": "Link",
			"options": "Request for Quotation",
			"width": 150,
		},
	]

	if filters.get("group_by") == "Group by Item":
		group_by_columns.reverse()

	columns[0:0] = group_by_columns  # add positioned group by columns to the report
	return columns


def get_message():
	return """<span class="indicator">
		Valid till : &nbsp;&nbsp;
		</span>
		<span class="indicator orange">
		Expires in a week or less
		</span>
		&nbsp;&nbsp;
		<span class="indicator red">
		Expires today / Already Expired
		</span>"""
