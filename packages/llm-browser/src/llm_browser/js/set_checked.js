// Set the checked state of a checkbox by element ID.
// Args: { id: string, checked: boolean }
(args) => {
  document.getElementById(args.id).checked = args.checked;
}
