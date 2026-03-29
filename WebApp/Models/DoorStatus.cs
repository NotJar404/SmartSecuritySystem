namespace WebApp.Models
{
    public class DoorStatus
    {
        public int Id { get; set; }

        public string DoorName { get; set; }
        public bool IsLocked { get; set; }
        public string Location { get; set; }
    }
}